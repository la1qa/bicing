"""Project paths and runtime settings."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

DATA_DIR = Path("/mnt/sandisk128_1/Bicing/data")
RAW_DATA_DIR = DATA_DIR / "raw"
HISTORICAL_DIR = RAW_DATA_DIR / "historical"
METADATA_ARCHIVE_DIR = RAW_DATA_DIR / "metadata"
SAMPLES_DIR = RAW_DATA_DIR / "samples"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
EXTRACTED_DATA_DIR = PROCESSED_DATA_DIR / "extracted"
METADATA_EXTRACTED_DIR = PROCESSED_DATA_DIR / "metadata_extracted"
DATABASE_PATH = DATA_DIR / "bicing.sqlite"

TIMEZONE = "Europe/Madrid"
DATA_START_DATE = "2024-01-01"

# Backwards-compatible names used by the original scripts.
ROOT = PROJECT_ROOT
DB_PATH = DATABASE_PATH
ARCHIVE_DIR = HISTORICAL_DIR