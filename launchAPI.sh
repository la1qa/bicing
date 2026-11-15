#!/usr/bin/env bash
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"

echo "Database ready: $ROOT_DIR/data/bicing.sqlite"
echo "Starting local API at http://$API_HOST:$API_PORT ..."
exec "$PYTHON" -m uvicorn src.api.main:app \
    --host "$API_HOST" \
    --port "$API_PORT"
