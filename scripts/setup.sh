#!/usr/bin/env bash
# One-time setup for Revive on macOS and Linux (P3). Safe to run again:
# every step checks first and skips what's already done.
#   scripts/setup.sh [--verbose]
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
LOG="$ROOT/setup.log"
VERBOSE=0
[ "${1:-}" = "--verbose" ] && VERBOSE=1
: > "$LOG"

OS=$(uname -s)
ESRGAN_VER=v0.2.5.0
case "$OS" in
  Darwin) ESRGAN_ZIP=realesrgan-ncnn-vulkan-20220424-macos.zip ;;
  *)      ESRGAN_ZIP=realesrgan-ncnn-vulkan-20220424-ubuntu.zip ;;
esac

say()  { printf '%s\n' "$*"; }
step() { printf '\nStep %s of 6: %s\n' "$1" "$2"; }
# Run a command quietly (into setup.log), or in full with --verbose.
run()  { if [ $VERBOSE = 1 ]; then "$@" 2>&1 | tee -a "$LOG"; return "${PIPESTATUS[0]}"; else "$@" >>"$LOG" 2>&1; fi; }
fail() { say "  ✗ $*"; [ $VERBOSE = 1 ] || say "  (Details are in setup.log. Run 'scripts/setup.sh --verbose' to see everything.)"; exit 1; }
net_fail() { fail "$1 Check your internet and run setup again."; }

say "Setting up Revive. This only needs to happen once."
say "The first time it downloads about 7 GB, so it can take a while. Later runs are quick."

# --- a. Python ------------------------------------------------------------
step 1 "Checking for Python…"
SYS_PY=""
for c in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    SYS_PY=$(command -v "$c"); break
  fi
done
if [ -x venv/bin/python ]; then
  say "  ✓ Already set up ($(venv/bin/python --version))"
elif [ -n "$SYS_PY" ]; then
  say "  ✓ Found $("$SYS_PY" --version)"
else
  say "  ✗ Revive needs Python 3.11 or newer."
  say "    Get it from https://www.python.org/downloads/ , install it, then run setup again."
  exit 1
fi

# --- b. Packages ------------------------------------------------------------
step 2 "Installing the Python packages (the first time takes a few minutes)…"
if [ ! -x venv/bin/python ]; then
  run "$SYS_PY" -m venv venv || fail "Couldn't create the Python environment."
fi
PY="$ROOT/venv/bin/python"
REQ_HASH=$("$PY" -c "import hashlib;print(hashlib.sha256(open('requirements.txt','rb').read()).hexdigest())")
STAMP=venv/.revive-requirements
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$REQ_HASH" ] && "$PY" -c "import sys, importlib.util as u; sys.exit(not all(u.find_spec(m) for m in ('torch', 'basicsr', 'gfpgan', 'facexlib', 'fastapi', 'pillow_heif')))"; then
  say "  ✓ Already installed"
else
  run "$PY" -m pip install -q --upgrade pip setuptools wheel || net_fail "Couldn't update pip."
  if ! "$PY" -c "import torch, torchvision" 2>/dev/null; then
    say "  Getting PyTorch (about 200 MB)…"
    if [ "$OS" = Darwin ]; then
      run "$PY" -m pip install -q torch torchvision || net_fail "Couldn't install PyTorch."
    else
      run "$PY" -m pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cpu \
        || net_fail "Couldn't install PyTorch."
    fi
  fi
  run "$PY" scripts/install_basicsr.py || net_fail "Couldn't install the face-fixing library (basicsr)."
  run "$PY" -m pip install -q -r requirements.txt || net_fail "Couldn't install the Python packages."
  echo "$REQ_HASH" > "$STAMP"
  say "  ✓ Done"
fi

# --- c. Real-ESRGAN ---------------------------------------------------------
step 3 "Getting the photo sharpener…"
ESRGAN_BIN=$("$PY" -c "from backend import config; print(config.realesrgan_binary())")
if [ -x "$ESRGAN_BIN" ]; then
  say "  ✓ Already there"
else
  mkdir -p bin
  run curl -fL --retry 3 -o bin/esrgan.zip \
    "https://github.com/xinntao/Real-ESRGAN/releases/download/$ESRGAN_VER/$ESRGAN_ZIP" \
    || { rm -f bin/esrgan.zip; net_fail "Couldn't download the photo sharpener."; }
  run "$PY" -m zipfile -e bin/esrgan.zip bin/ || fail "Couldn't unpack the photo sharpener."
  rm -f bin/esrgan.zip
  ESRGAN_BIN=$("$PY" -c "from backend import config; print(config.realesrgan_binary())")
  chmod +x "$ESRGAN_BIN" 2>/dev/null
  [ "$OS" = Darwin ] && xattr -dr com.apple.quarantine bin 2>/dev/null
  [ -x "$ESRGAN_BIN" ] || fail "The photo sharpener didn't unpack where expected ($ESRGAN_BIN)."
  say "  ✓ Done"
fi

# --- d. Face weights --------------------------------------------------------
step 4 "Getting the face-fixing models (about 540 MB)…"
if "$PY" -c "import sys; from backend.pipeline.faces import WEIGHTS; sys.exit(not all(p.is_file() for p in WEIGHTS))"; then
  say "  ✓ Already there"
else
  if [ $VERBOSE = 1 ]; then
    "$PY" -m backend.pipeline.faces --download-weights || net_fail "Couldn't download the face-fixing models."
  else
    # Show the per-file lines so a long download doesn't look frozen.
    "$PY" -m backend.pipeline.faces --download-weights 2>>"$LOG" || net_fail "Couldn't download the face-fixing models."
  fi
  say "  ✓ Done"
fi

# --- e. Ollama + Gemma ------------------------------------------------------
step 5 "Getting the caption writer (Gemma, about 6 GB the first time)…"
if ! command -v ollama >/dev/null 2>&1; then
  say "  ✗ Revive uses a free app called Ollama to run Gemma on this computer."
  say "    Install it from https://ollama.com/download , then run setup again."
  exit 1
fi
if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null; then
  if [ "$OS" = Darwin ] && [ -d /Applications/Ollama.app ]; then
    open -a Ollama
  else
    nohup ollama serve >>"$LOG" 2>&1 &
  fi
  for _ in $(seq 30); do curl -sf http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done
fi
curl -sf http://127.0.0.1:11434/api/tags >/dev/null || fail "Ollama is installed but didn't start. Open the Ollama app, then run setup again."
GEMMA=$("$PY" -c "from backend import config; print(config.GEMMA_MODEL)")
if "$PY" -c "import sys; from backend.captions.gemma import gemma_available; sys.exit(not gemma_available())"; then
  say "  ✓ Already there ($GEMMA)"
else
  say "  Downloading $GEMMA…"
  ollama pull "$GEMMA" || net_fail "Couldn't download $GEMMA."
  say "  ✓ Done"
fi

# --- f. Self-check ----------------------------------------------------------
step 6 "Checking everything works…"
TORCH_CPP_LOG_LEVEL=ERROR "$PY" - <<'EOF'
import sys
from backend.pipeline.upscale import upscaler_available
from backend.pipeline.faces import faces_available
from backend.captions.gemma import gemma_available

checks = [
    ("Make sharper", upscaler_available, "run setup again"),
    ("Fix faces", faces_available, "run setup again"),
    ("Write captions", gemma_available, "open the Ollama app, then run setup again"),
]
ok = True
for name, fn, fix in checks:
    try:
        good = bool(fn())
    except Exception:
        good = False
    ok &= good
    print(f"  {name} " + ("✓" if good else f"✗ — {fix}"))
sys.exit(0 if ok else 1)
EOF
STATUS=$?
echo
if [ $STATUS = 0 ]; then
  say "All set! To use Revive, double-click 'Start Revive' (or run scripts/start.sh)."
else
  say "Revive will still work, just without the parts marked ✗."
fi
exit $STATUS
