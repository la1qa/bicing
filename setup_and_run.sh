#!/usr/bin/env bash
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

if [ ! -x "$ROOT_DIR/.venv/bin/python" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$ROOT_DIR/.venv"
fi
PYTHON="$ROOT_DIR/.venv/bin/python"

echo "Installing project dependencies..."
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r "$ROOT_DIR/requirements.txt"

BATCH_SIZE="${BICING_BATCH_SIZE:-5000}"
API_HOST="${BICING_API_HOST:-0.0.0.0}"
API_PORT="${BICING_API_PORT:-8000}"
DATA_START_DATE="${BICING_DATA_START_DATE:-2024-01-01}"
DATA_START_MONTH="$(printf '%s' "$DATA_START_DATE" | cut -c 1-7)"

echo "Removing data older than $DATA_START_DATE..."
"$PYTHON" -m src.cli prune --start-date "$DATA_START_DATE"

echo "Downloading historical station-status archives..."
"$PYTHON" -m src.cli download-timeline \
    --start-month "$DATA_START_MONTH" \
    --extracted "$ROOT_DIR/data/processed/extracted"

echo "Extracting station-status archives..."
"$PYTHON" -m src.cli extract

echo "Importing station metadata..."
"$PYTHON" -m src.cli import-live-metadata

echo "Importing station-status observations..."
"$PYTHON" -m src.cli import --batch-size "$BATCH_SIZE"