"""Gemma captions — PLACEHOLDER created by P1 in Phase 1. Owned by P3.

P3 replaces the real path with Gemma via Ollama (master §7.3, phase-2 P3 section).
Only the mock path (canned caption) is implemented here.
"""
from __future__ import annotations

import time
from pathlib import Path

from backend import config


def gemma_available() -> bool:
    return config.MOCK  # TODO(P3): ping Ollama and check config.GEMMA_MODEL is pulled


def caption_photo(src: Path) -> dict:
    """{"caption": str, "decade": str | None}. Raises on failure."""
    if config.MOCK:
        time.sleep(config.MOCK_STEP_SECONDS)
        return {"caption": "A family gathers together, smiling for the camera.", "decade": "1980s"}
    raise NotImplementedError("Captions are not implemented yet (P3).")
