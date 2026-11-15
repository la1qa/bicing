from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from fastapi.testclient import TestClient

from src.database.db import (
    Station,
    StationMetadataHistory,
    StationStatus,
    initialize_database,
    session_scope,
)
from src.ingestion.import_data import import_files, import_metadata_files
from src.ingestion.download import _timeline_resources, download_metadata_archives
from src.processing.transformations import normalize_timestamp
from src.processing.validation import validate_status_frame
from src.api.main import create_app

def test_timestamp_normalizes_to_utc():
    assert normalize_timestamp("2024-01-01T10:00:00+01:00").hour == 9

def test_validation_reports_negative_values():
    report = validate_status_frame(pd.DataFrame([{"station_id": "1", "timestamp": "x", "docks_available": -1}]))
    assert "Negative values in docks_available" in report.errors

def test_import_is_repeatable(tmp_path):
    source = tmp_path / "sample.csv"
    source.write_text(
        "station_id,last_updated,num_bikes_available_types.mechanical,num_bikes_available_types.ebike,num_docks_available\n"
        "1,1714514402,2,1,5\n", encoding="utf-8"
    )
    engine = initialize_database(tmp_path / "test.sqlite")
    assert import_files(engine, tmp_path).imported == 1
    assert import_files(engine, tmp_path).skipped == 1
    with session_scope(engine) as session:
        assert session.query(StationStatus).count() == 1


def test_import_processes_csv_in_configured_chunks(tmp_path):
    source = tmp_path / "chunked.csv"
    source.write_text(
        "station_id,last_updated,num_bikes_available_types.mechanical,num_bikes_available_types.ebike,num_docks_available\n"
        + "\n".join(f"{index},17145144{index:02d},1,2,3" for index in range(5)),
        encoding="utf-8",
    )
    engine = initialize_database(tmp_path / "chunked.sqlite")
    report = import_files(engine, tmp_path, batch_size=2)
    assert report.records_processed == 5
    assert report.imported == 5


def test_metadata_import_populates_current_and_history(tmp_path):
    source = tmp_path / "metadata.csv"
    source.write_text(
        "station_id,name,physical_configuration,lat,lon,altitude,capacity,last_updated\n"
        "1,Central,ELECTRICBIKESTATION,41.1,2.1,10,20,1714514402\n",
        encoding="utf-8",
    )
    engine = initialize_database(tmp_path / "metadata.sqlite")
    report = import_metadata_files(engine, tmp_path, batch_size=1)
    assert report.imported == 1
    with session_scope(engine) as session:
        station = session.get(Station, "1")
        assert station.name == "Central"
        assert station.capacity == 20
        assert session.query(StationMetadataHistory).count() == 1


def test_metadata_import_closes_changed_history_interval(tmp_path):
    first = tmp_path / "01_metadata.csv"
    second = tmp_path / "02_metadata.csv"
    first.write_text(
        "station_id,name,lat,lon,capacity,last_updated\n"
        "1,Old,41.1,2.1,20,1714514400\n",
        encoding="utf-8",
    )
    second.write_text(
        "station_id,name,lat,lon,capacity,last_updated\n"
        "1,New,41.2,2.2,25,1714600800\n",
        encoding="utf-8",
    )
    engine = initialize_database(tmp_path / "metadata-history.sqlite")
    assert import_metadata_files(engine, tmp_path).imported == 2
    with session_scope(engine) as session:
        history = session.query(StationMetadataHistory).order_by(
            StationMetadataHistory.valid_from
        ).all()
        assert len(history) == 2
        assert history[0].valid_to == history[1].valid_from
        assert history[1].valid_to is None


def test_timeline_resource_discovery_selects_status_archives(monkeypatch):
    class Response:
        def __init__(self):
            self.read_once = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return (
                b'{"success": true, "result": {"resources": ['
                b'{"name": "2026_05_Maig_BicingNou_ESTACIONS.7z", "url": "status"},'
                b'{"name": "2026_05_Maig_BicingNou_INFORMACIO.7z", "url": "metadata"}]}}'
            )

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    assert _timeline_resources() == [{
        "name": "2026_05_Maig_BicingNou_ESTACIONS.7z",
        "url": "status",
    }]


def test_latest_metadata_download_only_selects_newest_month(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.ingestion.download._metadata_resources",
        lambda: [
            {"name": "2025_12_Desembre_BicingNou_INFORMACIO.7z", "url": "old"},
            {"name": "2026_05_Maig_BicingNou_INFORMACIO.7z", "url": "latest"},
        ],
    )
    latest = tmp_path / "2026_05_Maig_BicingNou_INFORMACIO.7z"
    latest.write_bytes(b"already downloaded")
    results = download_metadata_archives(tmp_path, latest_only=True)
    assert [result.name for result in results] == [
        "2026_05_Maig_BicingNou_INFORMACIO.7z"
    ]
    assert results[0].downloaded is False
    assert latest.read_bytes() == b"already downloaded"


def test_database_schema_has_composite_status_index(tmp_path):
    engine = initialize_database(tmp_path / "schema.sqlite")
    indexes = inspect(engine).get_indexes("station_status")
    assert any(index["name"] == "ix_station_status_station_timestamp" for index in indexes)


def test_sqlite_connection_is_configured_for_foreign_keys_and_waits(tmp_path):
    engine = initialize_database(tmp_path / "pragmas.sqlite")
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert connection.execute(text("PRAGMA busy_timeout")).scalar() == 60000
        assert connection.execute(text("PRAGMA journal_mode")).scalar().lower() == "wal"


def test_timestamps_are_stored_and_returned_as_utc(tmp_path):
    engine = initialize_database(tmp_path / "utc.sqlite")
    with session_scope(engine) as session:
        session.add(Station(station_id="1"))
        session.add(
            StationStatus(
                station_id="1",
                timestamp=datetime(2024, 1, 1, 10, tzinfo=timezone(timedelta(hours=1))),
            )
        )
    with session_scope(engine) as session:
        timestamp = session.query(StationStatus).one().timestamp
        assert timestamp == datetime(2024, 1, 1, 9, tzinfo=timezone.utc)
        assert timestamp.tzinfo == timezone.utc


def test_metadata_history_has_unique_start_and_valid_range(tmp_path):
    engine = initialize_database(tmp_path / "history.sqlite")
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(IntegrityError):
        with session_scope(engine) as session:
            session.add(Station(station_id="1"))
            session.add(StationMetadataHistory(station_id="1", valid_from=start))
            session.add(StationMetadataHistory(station_id="1", valid_from=start))

    with pytest.raises(IntegrityError):
        with session_scope(engine) as session:
            session.add(StationMetadataHistory(
                station_id="1",
                valid_from=start,
                valid_to=start - timedelta(seconds=1),
            ))


def test_station_cannot_be_deleted_while_history_exists(tmp_path):
    engine = initialize_database(tmp_path / "delete.sqlite")
    with pytest.raises(IntegrityError):
        with session_scope(engine) as session:
            station = Station(station_id="1")
            station.metadata_history.append(
                StationMetadataHistory(
                    valid_from=datetime(2024, 1, 1, tzinfo=timezone.utc)
                )
            )
            session.add(station)
            session.flush()
            session.delete(station)


def test_api_health_stats_and_timestamp_filtering(tmp_path):
    database = tmp_path / "api.sqlite"
    engine = initialize_database(database)
    with session_scope(engine) as session:
        session.add(Station(station_id="1", name="Test station"))
        session.add_all([
            StationStatus(
                station_id="1",
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                docks_available=3,
            ),
            StationStatus(
                station_id="1",
                timestamp=datetime(2024, 1, 2, tzinfo=timezone.utc),
                docks_available=4,
            ),
        ])
    client = TestClient(create_app(database))
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/stats").json()["observation_count"] == 2
    response = client.get("/stations/1/status?start=2024-01-02T00:00:00Z")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_temporal_api_snapshot_station_and_changes(tmp_path):
    database = tmp_path / "temporal-api.sqlite"
    engine = initialize_database(database)
    first = datetime(2024, 1, 1, tzinfo=timezone.utc)
    second = datetime(2024, 1, 2, tzinfo=timezone.utc)
    with session_scope(engine) as session:
        session.add(Station(
            station_id="1", name="Current", latitude=41.2, longitude=2.2, capacity=25
        ))
        session.add_all([
            StationMetadataHistory(
                station_id="1", valid_from=first, valid_to=second,
                name="Old", latitude=41.1, longitude=2.1, capacity=20,
            ),
            StationMetadataHistory(
                station_id="1", valid_from=second,
                name="Current", latitude=41.2, longitude=2.2, capacity=25,
            ),
            StationStatus(
                station_id="1", timestamp=first,
                mechanical_bikes_available=2, ebikes_available=1, docks_available=5,
            ),
            StationStatus(
                station_id="1", timestamp=second,
                mechanical_bikes_available=4, ebikes_available=0, docks_available=3,
            ),
        ])
    client = TestClient(create_app(database))
    assert client.get("/stations/1").json()["name"] == "Current"
    assert len(client.get("/snapshots").json()["items"]) == 2
    snapshot = client.get("/snapshots/2024-01-01T00:00:00Z").json()
    assert snapshot["items"][0]["name"] == "Old"
    assert snapshot["items"][0]["capacity"] == 20
    changes = client.get("/stations/1/changes").json()["items"]
    assert changes[0]["mechanical_bikes_change"] is None
    assert changes[1]["mechanical_bikes_change"] == 2
    assert changes[1]["ebikes_change"] == -1
    assert changes[1]["docks_change"] == -2


def test_status_source_allows_same_timestamp_from_distinct_sources(tmp_path):
    engine = initialize_database(tmp_path / "sources.sqlite")
    timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with session_scope(engine) as session:
        session.add(Station(station_id="1"))
        session.add_all([
            StationStatus(station_id="1", timestamp=timestamp, source="historical"),
            StationStatus(station_id="1", timestamp=timestamp, source="live"),
        ])
    with session_scope(engine) as session:
        assert session.query(StationStatus).count() == 2
