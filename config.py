"""Project paths and runtime settings."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
HISTORICAL_DIR = RAW_DATA_DIR / "historical"
SAMPLES_DIR = RAW_DATA_DIR / "samples"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
EXTRACTED_DATA_DIR = PROCESSED_DATA_DIR / "extracted"
DATABASE_PATH = DATA_DIR / "bicing.sqlite"
TIMEZONE = "Europe/Madrid"

# Backwards-compatible names used by the original scripts.
ROOT = PROJECT_ROOT
DB_PATH = DATABASE_PATH
ARCHIVE_DIR = HISTORICAL_DIR