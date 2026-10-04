"""Caption every photo in a folder with the real Gemma model (P3 dev tool).

    REVIVE_GEMMA_MODEL=gemma4:e4b-it-qat python -m backend.captions.try_captions samples/public/
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from backend import config
from backend.captions.gemma import caption_photo, gemma_available

EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    folder = Path(argv[0] if argv else "samples/public")
    photos = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS)
    print(f"model={config.GEMMA_MODEL} mock={config.MOCK} available={gemma_available()} photos={len(photos)}")
    total = 0.0
    for p in photos:
        t = time.perf_counter()
        try:
            r = caption_photo(p)
            line = f"{r['decade'] or '-':>7}  {r['caption']}"
        except Exception as e:
            line = f"FAILED  {e}"
        dt = time.perf_counter() - t
        total += dt
        print(f"{p.name:36} {dt:6.1f}s  {line}", flush=True)
    if photos:
        print(f"total {total:.1f}s, avg {total / len(photos):.1f}s/photo")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
