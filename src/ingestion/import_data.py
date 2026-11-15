"""Chunked, repeatable import of supported JSON and CSV source files."""

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import time
from typing import Any, Iterator

import pandas as pd
from sqlalchemy.dialects.sqlite import insert

from src.database.db import Station, StationMetadataHistory, StationStatus, session_scope
from src.processing.transformations import normalize_columns, normalize_timestamp
from src.processing.validation import validate_status_frame

LOGGER = logging.getLogger(__name__)
DEFAULT_BATCH_SIZE = 5_000
DEFAULT_MAPPING = {
    "station_id": "station_id",
    "timestamp": "timestamp",
    "mechanical_bikes_available": "mechanical_bikes_available",
    "ebikes_available": "ebikes_available",
    "docks_available": "docks_available",
    "is_installed": "is_installed",
    "is_renting": "is_renting",
    "is_returning": "is_returning",
    "name": "name",
    "latitude": "latitude",
    "longitude": "longitude",
    "capacity": "capacity",
    "physical_configuration": "physical_configuration",
}
METADATA_ALIASES = {
    "lat": "latitude",
    "lon": "longitude",
    "last_updated": "valid_from",
}
SOURCE_ALIASES = {
    "last_updated": "timestamp",
    "num_bikes_available_types_mechanical": "mechanical_bikes_available",
    "num_bikes_available_types_ebike": "ebikes_available",
    "num_docks_available": "docks_available",
}


@dataclass
class ImportReport:
    """Counters and timings produced by an import run."""

    imported: int = 0
    skipped: int = 0
    records_processed: int = 0
    parse_seconds: float = 0.0
    validation_seconds: float = 0.0
    insert_seconds: float = 0.0
    total_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def records_per_second(self) -> float:
        """Return throughput based on all processed records."""
        return self.records_processed / self.total_seconds if self.total_seconds else 0.0


def _read_json(path: Path) -> pd.DataFrame:
    """Read a JSON document; large JSON arrays should be converted to CSV first."""
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"].get("stations", payload["data"])
    if isinstance(payload, dict):
        payload = payload.get("stations", [payload])
    return pd.json_normalize(payload)


def _iter_frames(path: Path, batch_size: int) -> Iterator[pd.DataFrame]:
    """Yield bounded source frames without loading a large CSV into RAM."""
    if path.suffix.lower() == ".csv":
        yield from pd.read_csv(path, chunksize=batch_size, low_memory=False)
    elif path.suffix.lower() == ".json":
        yield _read_json(path)
    else:
        raise ValueError(f"Unsupported file type: {path.suffix}")


def _prepare_frame(frame: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Normalize source column names and apply configured aliases."""
    normalized = normalize_columns(frame)
    rename = {
        **SOURCE_ALIASES,
        **{source: target for target, source in mapping.items() if source in normalized.columns},
    }
    return normalized.rename(columns=rename)


def import_files(
    engine,
    directory: str | Path,
    mapping: dict[str, str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ImportReport:
    """Import files in bounded batches with database-level duplicate handling.

    Each batch is committed independently. This bounds memory and lock duration;
    rerunning after an interruption is safe because the database unique
    constraint rejects observations already committed.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    report = ImportReport()
    mapping = {**DEFAULT_MAPPING, **(mapping or {})}
    started = time.perf_counter()
    for path in sorted(Path(directory).rglob("*")):
        if path.suffix.lower() not in {".csv", ".json"}:
            continue
        try:
            for source_frame in _iter_frames(path, batch_size):
                parse_started = time.perf_counter()
                frame = _prepare_frame(source_frame, mapping)
                report.parse_seconds += time.perf_counter() - parse_started
                report.records_processed += len(frame)
                validation_started = time.perf_counter()
                if "station_id" not in frame or "timestamp" not in frame:
                    report.errors.append(f"{path.name}: missing station_id or timestamp")
                    report.skipped += len(frame)
                    continue
                validation = validate_status_frame(frame)
                report.errors.extend(f"{path.name}: {error}" for error in validation.errors)
                valid = frame["station_id"].notna() & frame["timestamp"].notna()
                report.skipped += int((~valid).sum())
                frame = frame.loc[valid]
                report.validation_seconds += time.perf_counter() - validation_started
                records = _records_from_frame(frame, path.name, report)
                if not records:
                    continue
                insert_started = time.perf_counter()
                inserted, duplicates = _insert_batch(engine, records)
                report.insert_seconds += time.perf_counter() - insert_started
                report.imported += inserted
                report.skipped += duplicates
                LOGGER.info(
                    "%s: processed=%d imported=%d duplicates=%d",
                    path.name,
                    report.records_processed,
                    report.imported,
                    report.skipped,
                )
        except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
            LOGGER.error("Could not import %s: %s", path, exc)
            report.errors.append(f"{path.name}: {exc}")
    report.total_seconds = time.perf_counter() - started
    return report


def import_metadata_files(
    engine,
    directory: str | Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> ImportReport:
    """Import station metadata into current and versioned metadata tables."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    report = ImportReport()
    started = time.perf_counter()
    for path in sorted(Path(directory).rglob("*.csv")):
        try:
            for source_frame in _iter_frames(path, batch_size):
                frame = normalize_columns(source_frame).rename(columns=METADATA_ALIASES)
                report.records_processed += len(frame)
                required = {"station_id", "valid_from"}
                if not required.issubset(frame.columns):
                    report.errors.append(f"{path.name}: missing {sorted(required - set(frame.columns))}")
                    report.skipped += len(frame)
                    continue
                valid = frame["station_id"].notna() & frame["valid_from"].notna()
                report.skipped += int((~valid).sum())
                rows = []
                for row in frame.loc[valid].to_dict("records"):
                    valid_from = normalize_timestamp(row["valid_from"])
                    if valid_from is None:
                        report.skipped += 1
                        continue
                    rows.append({
                        "station_id": _normalize_station_id(row["station_id"]),
                        "valid_from": valid_from,
                        "latitude": _number_or_none(row.get("latitude")),
                        "longitude": _number_or_none(row.get("longitude")),
                        "altitude": _number_or_none(row.get("altitude")),
                        "capacity": _integer_or_none(row.get("capacity")),
                        "name": _optional_value(row.get("name")),
                        "physical_configuration": _optional_value(row.get("physical_configuration")),
                    })
                for start in range(0, len(rows), batch_size):
                    inserted, duplicates = _insert_metadata_batch(
                        engine,
                        rows[start:start + batch_size],
                    )
                    report.imported += inserted
                    report.skipped += duplicates
        except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
            LOGGER.error("Could not import metadata %s: %s", path, exc)
            report.errors.append(f"{path.name}: {exc}")
    report.total_seconds = time.perf_counter() - started
    return report


def _records_from_frame(frame: pd.DataFrame, source_file: str, report: ImportReport) -> list[dict[str, Any]]:
    records = []
    for row in frame.to_dict("records"):
        timestamp = normalize_timestamp(row["timestamp"])
        if timestamp is None:
            report.skipped += 1
            continue
        records.append({
            "station_id": _normalize_station_id(row["station_id"]),
            "timestamp": timestamp,
            "source_file": source_file,
            **{
                key: _optional_value(row.get(key))
                for key in (
                    "mechanical_bikes_available", "ebikes_available", "docks_available",
                    "is_installed", "is_renting", "is_returning",
                )
            },
        })
    return records


def _insert_batch(engine, records: list[dict[str, Any]]) -> tuple[int, int]:
    """Insert one batch and return inserted and duplicate counts."""
    with session_scope(engine) as session:
        stations = [{"station_id": station_id} for station_id in {row["station_id"] for row in records}]
        session.execute(insert(Station).on_conflict_do_nothing(index_elements=["station_id"]), stations)
        result = session.execute(
            insert(StationStatus)
            .on_conflict_do_nothing(index_elements=["station_id", "timestamp"])
            .returning(StationStatus.id),
            records,
        )
        inserted = len(result.scalars().all())
    return inserted, len(records) - inserted


def _insert_metadata_batch(engine, records: list[dict[str, Any]]) -> tuple[int, int]:
    """Upsert current metadata and append each new metadata version."""
    if not records:
        return 0, 0
    with session_scope(engine) as session:
        station_values = [
            {
                "station_id": row["station_id"],
                "name": row["name"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "altitude": row["altitude"],
                "capacity": row["capacity"],
                "physical_configuration": row["physical_configuration"],
                "last_updated": row["valid_from"],
            }
            for row in records
        ]
        station_insert = insert(Station).values(station_values)
        session.execute(
            station_insert.on_conflict_do_update(
                index_elements=["station_id"],
                set_={
                    "name": station_insert.excluded.name,
                    "latitude": station_insert.excluded.latitude,
                    "longitude": station_insert.excluded.longitude,
                    "altitude": station_insert.excluded.altitude,
                    "capacity": station_insert.excluded.capacity,
                    "physical_configuration": station_insert.excluded.physical_configuration,
                    "last_updated": station_insert.excluded.last_updated,
                },
            )
        )
        history_values = [
            {key: row[key] for key in (
                "station_id", "valid_from", "latitude", "longitude",
                "capacity", "name", "physical_configuration",
            )}
            for row in records
        ]
        history_insert = (
            insert(StationMetadataHistory)
            .on_conflict_do_nothing(index_elements=["station_id", "valid_from"])
            .returning(StationMetadataHistory.id)
        )
        inserted = len(session.execute(history_insert, history_values).scalars().all())
    return inserted, len(records) - inserted


def _normalize_station_id(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _optional_value(value: Any) -> Any:
    return None if value is None or pd.isna(value) else value


def _number_or_none(value: Any) -> float | None:
    numeric = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(numeric) else float(numeric)


def _integer_or_none(value: Any) -> int | None:
    numeric = _number_or_none(value)
    return None if numeric is None else int(numeric)
