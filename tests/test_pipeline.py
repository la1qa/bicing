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
