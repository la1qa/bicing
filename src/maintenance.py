"""Maintenance operations for keeping the local dataset within its time window."""

from dataclasses import dataclass
from pathlib import Path
import re
import shutil

from sqlalchemy import delete

from src.database.db import StationMetadataHistory, StationStatus, session_scope
from src.processing.transformations import normalize_timestamp

_MONTH_PREFIX = re.compile(r"^(\d{4}-\d{2}|\d{4}_\d{2})")


@dataclass(frozen=True)
class PruneReport:
    """Counts of removed database rows and filesystem entries."""

    status_rows: int
    metadata_rows: int
    files: int
    directories: int


def prune_before(
    engine,
    start_date: str,
    *,
    historical_dir: str | Path,
    extracted_dir: str | Path,
    metadata_dir: str | Path,
    metadata_extracted_dir: str | Path,
) -> PruneReport:
    """Remove records and monthly source data older than ``start_date``."""
    start = normalize_timestamp(start_date)
    if start is None:
        raise ValueError(f"Invalid start date: {start_date}")
    start_month = start.strftime("%Y_%m")
    with session_scope(engine) as session:
        status_rows = session.execute(
            delete(StationStatus).where(StationStatus.timestamp < start)
        ).rowcount or 0
        metadata_rows = session.execute(
            delete(StationMetadataHistory).where(
                StationMetadataHistory.valid_from < start
            )
        ).rowcount or 0

    files = 0
    directories = 0
    for directory in (
        Path(historical_dir),
        Path(extracted_dir),
        Path(metadata_dir),
        Path(metadata_extracted_dir),
    ):
        removed_files, removed_directories = _remove_old_entries(directory, start_month)
        files += removed_files
        directories += removed_directories
    return PruneReport(status_rows, metadata_rows, files, directories)


def _remove_old_entries(directory: Path, start_month: str) -> tuple[int, int]:
    """Remove only direct monthly entries before the configured month."""
    if not directory.exists():
        return 0, 0
    removed_files = 0
    removed_directories = 0
    for entry in directory.iterdir():
        match = _MONTH_PREFIX.match(entry.name)
        if match is None:
            continue
        month = match.group(1).replace("-", "_")
        if month >= start_month:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
            removed_directories += 1
        elif entry.is_file():
            entry.unlink()
            removed_files += 1
    return removed_files, removed_directories
