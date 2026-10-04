#!/usr/bin/env bash
# Dev server in mock mode (no AI models needed) with auto-reload. Owned by P1.
# Usage: scripts/dev.sh      then open http://localhost:8765
set -e
cd "$(dirname "$0")/.."

PY=python
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi
if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe; fi

REVIVE_MOCK=1 exec "$PY" -m uvicorn backend.app:app --reload --port 8765 "$@"
