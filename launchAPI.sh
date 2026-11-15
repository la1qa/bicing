#!/usr/bin/env bash
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON="${BICING_PYTHON:-$ROOT_DIR/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    echo "Python virtual environment not found at $PYTHON." >&2
    echo "Run sh setup_and_run.sh first, or set BICING_PYTHON." >&2
    exit 1
fi

API_HOST="${BICING_API_HOST:-0.0.0.0}"
API_PORT="${BICING_API_PORT:-8000}"

echo "Database ready: $ROOT_DIR/data/bicing.sqlite"
echo "Starting local API at http://$API_HOST:$API_PORT ..."
exec "$PYTHON" -m uvicorn src.api.main:app \
    --host "$API_HOST" \
    --port "$API_PORT"
