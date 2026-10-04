"""Try the upscaler on files or folders and print timings (P1).

    python -m backend.pipeline.try_upscale samples/public/x.jpg [more files or folders] [--scale 2|4]

Results go to data/try_upscale/. Uses the real binary unless REVIVE_MOCK=1.
Only use samples/public/ (master §9).
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from backend import config
from backend.pipeline.upscale import open_image, upscale, upscaler_available

EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".bmp", ".tif", ".tiff"}


def _collect(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.suffix.lower() in EXTS)
        else:
            out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--scale", type=int, choices=(2, 4), default=4)
    ap.add_argument("--out", type=Path, default=config.DATA_DIR / "try_upscale")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="  %(name)s: %(message)s")

    print(f"mock={config.MOCK}  binary={config.realesrgan_binary()}  available={upscaler_available()}", flush=True)
    files = _collect(args.paths)
    if not files:
        print("No photos found.", flush=True)
        return 1
    failures, total = 0, 0.0
    for f in files:
        dst = args.out / f"{f.stem}_x{args.scale}.png"
        try:
            w, h = open_image(f).size
            t0 = time.perf_counter()
            ow, oh = upscale(f, dst, scale=args.scale)
            secs = time.perf_counter() - t0
            total += secs
            print(f"OK   {f.name}: {w}x{h} -> {ow}x{oh} in {secs:.1f}s  ({dst})", flush=True)
        except Exception as e:  # report and keep going, like the job runner
            failures += 1
            print(f"FAIL {f.name}: {type(e).__name__}: {e}", flush=True)
    print(f"{len(files) - failures}/{len(files)} ok, {total:.1f}s total", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
