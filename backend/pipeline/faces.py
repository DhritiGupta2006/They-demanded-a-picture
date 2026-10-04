"""Face restoration — PLACEHOLDER created by P1 in Phase 1. Owned by P3.

P3 replaces the real path with GFPGAN v1.4 (master §7.3, phase-2 P3 section).
Only the mock path is implemented here so mock mode runs end-to-end.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from backend import config


def faces_available() -> bool:
    return config.MOCK  # TODO(P3): real GFPGAN check


def restore_faces(src: Path, dst: Path) -> int:
    """Number of faces restored; copies src -> dst if 0. Raises on failure."""
    if config.MOCK:
        time.sleep(config.MOCK_STEP_SECONDS)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return 0
    raise NotImplementedError("Face restoration is not implemented yet (P3).")
