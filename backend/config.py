"""Paths and switches for the Revive backend (P1).

Everything is overridable with environment variables so tests and the
setup scripts can point the app somewhere else without code changes.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"
BIN_DIR = Path(os.environ.get("REVIVE_BIN_DIR", ROOT / "bin"))
MODELS_DIR = Path(os.environ.get("REVIVE_MODELS_DIR", ROOT / "models"))
SAMPLES_DIR = ROOT / "samples"
DATA_DIR = Path(os.environ.get("REVIVE_DATA_DIR", ROOT / "data"))
JOBS_DIR = DATA_DIR / "jobs"

HOST = "127.0.0.1"
PORT = 8765

# Mock mode: same API and progress, no AI models (master §7.4).
MOCK = _flag("REVIVE_MOCK")
MOCK_STEP_SECONDS = float(os.environ.get("REVIVE_MOCK_DELAY", "0.5"))

# --- Upscaling (Real-ESRGAN ncnn-vulkan) ---------------------------------
REALESRGAN_MODEL = "realesrgan-x4plus"
REALESRGAN_EXE_NAME = "realesrgan-ncnn-vulkan.exe" if sys.platform == "win32" else "realesrgan-ncnn-vulkan"
UPSCALE_MAX_INPUT_SIDE = 2500  # shrink bigger inputs first so output stays reasonable
UPSCALE_RETRY_TILE = 128       # tile size for the retry after an auto-tile (-t 0) failure
UPSCALE_TIMEOUT_SECONDS = 1800  # a 2500px input at 4x takes ~25 min on an Intel UHD 620


def realesrgan_binary() -> Path:
    """Location of the OS-specific Real-ESRGAN binary (may not exist)."""
    override = os.environ.get("REVIVE_REALESRGAN_BIN")
    if override:
        return Path(override)
    direct = BIN_DIR / REALESRGAN_EXE_NAME
    if direct.exists():
        return direct
    # Release zips sometimes unpack into a subfolder.
    for found in sorted(BIN_DIR.glob(f"*/{REALESRGAN_EXE_NAME}")):
        return found
    return direct


def realesrgan_models_dir() -> Path:
    return realesrgan_binary().parent / "models"


# --- Other modules (owned by P3; settings live here so there is one config) --
GEMMA_MODEL = os.environ.get("REVIVE_GEMMA_MODEL", "gemma4:e4b-it-qat")
CAPTION_MAX_SIDE = 1024
