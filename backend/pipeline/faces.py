"""Face restoration with GFPGAN v1.4 on the CPU (P3).

Weights live in models/ and are fetched once by setup
(`python -m backend.pipeline.faces --download-weights`); nothing downloads at
run time, so it works offline.

    python -m backend.pipeline.faces samples/public/   # writes samples/out-faces/
"""
from __future__ import annotations

import logging
import shutil
import sys
import threading
import time
import urllib.request
from pathlib import Path

from backend import config

log = logging.getLogger(__name__)

FRIENDLY_ERROR = "Couldn't fix the faces in this photo."
# How strongly GFPGAN's face replaces the original (0 = untouched, 1 = full GFPGAN).
# Chosen on old public-domain photos so faces still look like themselves; see post-notes.
WEIGHT = 0.5

FACEXLIB_DIR = config.MODELS_DIR / "facexlib"
WEIGHTS = {
    config.MODELS_DIR / "GFPGANv1.4.pth":
        "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
    FACEXLIB_DIR / "detection_Resnet50_Final.pth":
        "https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth",
    FACEXLIB_DIR / "parsing_parsenet.pth":
        "https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth",
}

_restorer = None
_lock = threading.Lock()


def _import_gfpgan():
    import torchvision.transforms.functional as F

    # basicsr 1.4.2 imports a torchvision module that newer torchvision removed.
    sys.modules.setdefault("torchvision.transforms.functional_tensor", F)
    import gfpgan.utils

    return gfpgan.utils


def faces_available() -> bool:
    if config.MOCK:
        return True
    if not all(p.is_file() for p in WEIGHTS):
        return False
    try:
        _import_gfpgan()
        return True
    except Exception:
        return False


def _get_restorer():
    global _restorer
    with _lock:
        if _restorer is None:
            gu = _import_gfpgan()
            orig_helper = gu.FaceRestoreHelper

            def helper(*args, **kwargs):
                # GFPGANer hardcodes model_rootpath='gfpgan/weights' (relative to the cwd)
                # and facexlib downloads into it; point it at our pre-fetched weights.
                kwargs["model_rootpath"] = str(FACEXLIB_DIR)
                return orig_helper(*args, **kwargs)

            gu.FaceRestoreHelper = helper
            try:
                _restorer = gu.GFPGANer(
                    model_path=str(config.MODELS_DIR / "GFPGANv1.4.pth"),
                    upscale=1, arch="clean", channel_multiplier=2, bg_upsampler=None, device="cpu",
                )
            finally:
                gu.FaceRestoreHelper = orig_helper
        return _restorer


def _save(img, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.suffix.lower() in (".jpg", ".jpeg"):
        img.save(dst, quality=95)
    else:
        img.save(dst)


def restore_faces(src: Path, dst: Path) -> int:
    """Number of faces restored; copies src -> dst if 0. Raises on failure."""
    if config.MOCK:
        time.sleep(config.MOCK_STEP_SECONDS)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return 0

    src, dst = Path(src), Path(dst)
    try:
        import numpy as np
        from PIL import Image, ImageOps

        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except ImportError:
            pass

        with Image.open(src) as im:
            rgb = np.asarray(ImageOps.exif_transpose(im).convert("RGB"))
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])

        restorer = _get_restorer()
        with _lock:  # GFPGANer keeps per-call state in its face helper
            _, restored, out = restorer.enhance(
                bgr, has_aligned=False, only_center_face=False, paste_back=True, weight=WEIGHT)

        if not restored or out is None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            return 0
        _save(Image.fromarray(np.ascontiguousarray(out[:, :, ::-1])), dst)
        return len(restored)
    except Exception:
        log.exception("faces: failed on %s", src)
        raise RuntimeError(FRIENDLY_ERROR)


def download_weights() -> bool:
    """Fetch any missing weight files. Returns False if a download failed."""
    ok = True
    for path, url in WEIGHTS.items():
        if path.is_file():
            print(f"  already have {path.name}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(path.suffix + ".part")
        print(f"  downloading {path.name} …", flush=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as resp, open(part, "wb") as f:
                shutil.copyfileobj(resp, f, 1 << 20)
            part.replace(path)
        except Exception as e:
            part.unlink(missing_ok=True)
            print(f"  couldn't download {path.name}: {e}")
            ok = False
    return ok


def _try_folder(folder: Path) -> None:
    out_dir = config.SAMPLES_DIR / "out-faces"
    exts = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
    print(f"available={faces_available()} weight={WEIGHT} -> {out_dir}")
    for p in sorted(x for x in folder.iterdir() if x.suffix.lower() in exts):
        t = time.perf_counter()
        try:
            n = restore_faces(p, out_dir / (p.stem + ".png"))
            msg = f"{n} faces"
        except Exception as e:
            msg = f"FAILED {e}"
        print(f"{p.name:36} {time.perf_counter() - t:6.1f}s  {msg}", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    if sys.argv[1:2] == ["--download-weights"]:
        sys.exit(0 if download_weights() else 1)
    _try_folder(Path(sys.argv[1] if len(sys.argv) > 1 else "samples/public"))
