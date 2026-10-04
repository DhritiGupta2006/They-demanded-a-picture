#!/usr/bin/env bash
# Start Revive and open it in the browser (macOS and Linux) (P3).
set -uo pipefail
cd "$(dirname "$0")/.."
unset REVIVE_MOCK

PY=venv/bin/python
URL=http://localhost:8765
if [ ! -x "$PY" ]; then
  echo "Please run setup first (scripts/setup.sh, or double-click 'Setup Revive')."
  exit 1
fi

open_browser() {
  if [ "$(uname -s)" = Darwin ]; then open "$URL"; else xdg-open "$URL" >/dev/null 2>&1 || echo "Open $URL in your browser."; fi
}

# Already running? Just open it.
if curl -sf "$URL/api/health" >/dev/null 2>&1; then
  echo "Revive is already running. Opening it in your browser."
  open_browser
  exit 0
fi

# Make sure Ollama (which runs Gemma) is up.
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && command -v ollama >/dev/null 2>&1; then
  if [ "$(uname -s)" = Darwin ] && [ -d /Applications/Ollama.app ]; then
    open -a Ollama
  else
    nohup ollama serve >/dev/null 2>&1 &
  fi
fi

echo "Starting Revive…"
mkdir -p data
# Only ever listen on this computer (127.0.0.1), never the network.
TORCH_CPP_LOG_LEVEL=ERROR "$PY" -m uvicorn backend.app:app --host 127.0.0.1 --port 8765 >data/revive.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null; exit 0' INT TERM HUP

for _ in $(seq 60); do
  curl -sf "$URL/api/health" >/dev/null 2>&1 && break
  if ! kill -0 $SERVER 2>/dev/null; then
    echo "Revive couldn't start. Try running setup again. (Details: data/revive.log)"
    exit 1
  fi
  sleep 0.5
done

open_browser
echo
echo "Revive is running. Leave this window open while you use it. Close it when you're done."
wait $SERVER
