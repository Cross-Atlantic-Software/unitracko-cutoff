#!/usr/bin/env bash
# Launch the Streamlit app using the project's virtualenv interpreter, never the
# system Python. Avoids `ModuleNotFoundError: No module named 'duckdb'` caused by
# running the global `streamlit` (which uses /usr/bin/python3 without our deps).
#
# Usage:
#   ./run.sh                 # serve on http://localhost:8502
#   ./run.sh 8501            # serve on a custom port
#   PORT=8600 ./run.sh       # alternative way to set the port
set -euo pipefail

cd "$(dirname "$0")"

# Prefer the Linux venv used on this machine, then a generic .venv.
if [ -x ".venv-linux/bin/streamlit" ]; then
  VENV=".venv-linux"
elif [ -x ".venv/bin/streamlit" ]; then
  VENV=".venv"
else
  echo "No virtualenv found. Create one first, e.g.:" >&2
  echo "  python -m venv .venv-linux && .venv-linux/bin/pip install -r requirements.txt" >&2
  exit 1
fi

PORT="${1:-${PORT:-8502}}"

echo "Starting Streamlit from $VENV on http://localhost:$PORT"
exec "$VENV/bin/streamlit" run app.py --server.port "$PORT"
