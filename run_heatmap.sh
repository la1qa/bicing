#!/bin/sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$ROOT_DIR"
if [ -n "${BICING_VIS_PYTHON:-}" ]; then
    PYTHON="$BICING_VIS_PYTHON"
elif [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
elif [ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]; then
    PYTHON="$ROOT_DIR/.venv/Scripts/python.exe"
else
    PYTHON="$ROOT_DIR/.venv/bin/python"
fi

if [ ! -x "$PYTHON" ]; then
    echo "Python environment not found at $PYTHON." >&2
    echo "Run setup_and_run.sh first or set BICING_VIS_PYTHON." >&2
    exit 1
fi

"$PYTHON" -m pip install -r "$ROOT_DIR/requirements-visualization.txt"
exec "$PYTHON" -m streamlit run "$ROOT_DIR/src/visualization/app.py"
