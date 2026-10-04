"""Upscaling with the realesrgan-ncnn-vulkan binary (P1). Contract: master §7.3.

Mock mode (REVIVE_MOCK=1) uses a plain Pillow LANCZOS resize instead.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageOps

from backend import config

try:  # HEIC/HEIF from iPhones
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - optional until requirements are installed
    pass

log = logging.getLogger("revive.upscale")

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def open_image(src: Path) -> Image.Image:
    """Open any supported photo (JPG/PNG/HEIC...), fix EXIF rotation, return RGB.

    Raises PIL.UnidentifiedImageError (or OSError) if it isn't a readable picture.
    """
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode != "RGB":
            im = im.convert("RGB")
        else:
            im.load()
    return im


def guard_input_size(im: Image.Image, name: str = "") -> Image.Image:
    """Shrink images whose longest side exceeds UPSCALE_MAX_INPUT_SIDE."""
    limit = config.UPSCALE_MAX_INPUT_SIDE
    if max(im.size) <= limit:
        return im
    before = im.size
    im = im.copy()
    im.thumbnail((limit, limit), Image.LANCZOS)
    log.info("input guard: shrank %s from %sx%s to %sx%s before upscaling", name or "image", *before, *im.size)
    return im


def upscaler_available() -> bool:
    if config.MOCK:
        return True
    exe = config.realesrgan_binary()
    models = config.realesrgan_models_dir()
    if not exe.is_file() or not (models / f"{config.REALESRGAN_MODEL}.param").is_file():
        return False
    try:
        # Note: the Windows build prints usage but exits with code 127 for -h,
        # so "runs cleanly" means: it launches and prints its usage text.
        proc = subprocess.run(
            [str(exe), "-h"], capture_output=True, text=True, errors="replace",
            timeout=10, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "Usage" in (proc.stdout + proc.stderr)


def _run_realesrgan(inp: Path, out: Path, tile: int) -> None:
    cmd = [
        str(config.realesrgan_binary()),
        "-i", str(inp), "-o", str(out),
        "-n", config.REALESRGAN_MODEL,
        "-m", str(config.realesrgan_models_dir()),
        "-s", "4", "-t", str(tile), "-f", "png",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, errors="replace",
        timeout=config.UPSCALE_TIMEOUT_SECONDS, creationflags=_NO_WINDOW,
    )
    # The binary sometimes exits 0 without writing anything (e.g. GPU out of memory).
    if proc.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        raise RuntimeError(f"realesrgan failed (exit {proc.returncode}, tile {tile}): {tail}")


def upscale(src: Path, dst: Path, scale: int = 4) -> tuple[int, int]:
    """Upscale src by 2 or 4 and write a PNG to dst. Returns (out_w, out_h). Raises on failure."""
    if scale not in (2, 4):
        raise ValueError(f"scale must be 2 or 4, got {scale!r}")
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    im = guard_input_size(open_image(src), src.name)
    target = (im.width * scale, im.height * scale)

    if config.MOCK:
        time.sleep(config.MOCK_STEP_SECONDS)
        im.resize(target, Image.LANCZOS).save(dst, "PNG")
        return target

    exe = config.realesrgan_binary()
    if not exe.is_file():
        raise FileNotFoundError(f"Real-ESRGAN binary not found at {exe}")

    with tempfile.TemporaryDirectory(prefix="revive-up-") as tmp:
        inp, out = Path(tmp) / "in.png", Path(tmp) / "out.png"
        im.save(inp, "PNG")  # normalised input: RGB, upright, any source format
        # A timeout is not retried: smaller tiles don't make a slow GPU faster,
        # they would only double the wait (seen on an Intel UHD 620).
        try:
            _run_realesrgan(inp, out, tile=0)
        except RuntimeError as first:
            log.warning("upscale of %s failed with auto tile, retrying with -t %d: %s",
                        src.name, config.UPSCALE_RETRY_TILE, first)
            out.unlink(missing_ok=True)
            _run_realesrgan(inp, out, tile=config.UPSCALE_RETRY_TILE)

        with Image.open(out) as res:
            res.load()
        # x4plus is a 4x model; for 2x we run 4x then halve.
        if res.size != target:
            res = res.resize(target, Image.LANCZOS)
        res.save(dst, "PNG")
    return target
