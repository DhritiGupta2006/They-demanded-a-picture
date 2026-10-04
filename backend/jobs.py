"""Job store and the single background worker (P1). Job object: master §7.2.

- One worker thread processes items sequentially (one GPU, one photo at a time).
- job.json is rewritten after every item status change, so a restart keeps finished work.
- Per item: original -> faces (original size) -> upscale -> caption (master §7.3).
  Each step raises on failure; we mark only that item failed and move on.
"""
from __future__ import annotations

import copy
import importlib
import json
import logging
import queue
import secrets
import threading
import time
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from backend import config
from backend.pipeline import upscale as upscale_mod

log = logging.getLogger("revive.jobs")

# Friendly, friend-facing errors (master §8). Never show a stack trace.
ERR_NOT_A_PHOTO = "This photo couldn't be opened. Is it a picture file?"
ERR_FACES = "We couldn't fix the faces in this photo. You can try again with \"Fix faces\" turned off."
ERR_UPSCALE = "We couldn't make this photo sharper. Try again, or try a smaller copy of the photo."
ERR_UPSCALER_MISSING = "The sharpening tool isn't installed yet. Please run the setup again."
ERR_CAPTION = "We couldn't write a caption for this photo. You can try again with \"Write captions\" turned off."
ERR_UNKNOWN = "Something went wrong with this photo. Please try it again."

_lock = threading.RLock()
_jobs: dict[str, dict] = {}
_queue: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None


# --- helpers -----------------------------------------------------------------

def job_dir(job_id: str) -> Path:
    return config.JOBS_DIR / job_id


def _save(job: dict) -> None:
    """Atomically write job.json. Caller holds _lock."""
    d = job_dir(job["job_id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "job.json.tmp"
    tmp.write_text(json.dumps(job, indent=2), encoding="utf-8")
    tmp.replace(d / "job.json")


def _update(job: dict, item: dict | None = None, **fields) -> None:
    with _lock:
        (item if item is not None else job).update(fields)
        _save(job)


def optional(module: str, name: str):
    """Function from another owner's module, or None if it can't be imported."""
    try:
        return getattr(importlib.import_module(module), name)
    except Exception:  # ImportError, or a broken optional dependency inside it
        log.warning("could not import %s.%s", module, name, exc_info=True)
        return None


def is_available(module: str, name: str) -> bool:
    fn = optional(module, name)
    if fn is None:
        return False
    try:
        return bool(fn())
    except Exception:
        log.warning("%s.%s() raised", module, name, exc_info=True)
        return False


def _clean_filename(name: str | None) -> str:
    # Folder drops may send "folder/sub/photo.jpg"; keep just the file name.
    return (name or "photo").replace("\\", "/").rsplit("/", 1)[-1] or "photo"


def _new_job_id() -> str:
    while True:
        job_id = secrets.token_hex(3)
        if job_id not in _jobs and not job_dir(job_id).exists():
            return job_id


# --- public API used by app.py --------------------------------------------

def create_job(files: list[tuple[str, bytes]], scale: int = 4, faces: bool = True, captions: bool = True) -> dict:
    """Store uploads as upright JPG/PNG originals, queue the job, return a snapshot."""
    job_id = _new_job_id()
    d = job_dir(job_id)
    (d / "original").mkdir(parents=True, exist_ok=True)

    items = []
    for i, (filename, data) in enumerate(files, start=1):
        item_id = f"{i:04d}"
        name = _clean_filename(filename)
        item = {
            "id": item_id, "filename": name, "status": "queued",
            "original_url": None, "result_url": None,
            "width": None, "height": None, "out_width": None, "out_height": None,
            "faces_found": None, "caption": None, "decade": None,
            "seconds": None, "error": None,
        }
        raw = d / "original" / f"{item_id}.upload"
        raw.write_bytes(data)
        try:
            # Normalise to something every browser can show (HEIC -> JPG) with EXIF rotation applied.
            im = upscale_mod.open_image(raw)
            ext = "png" if name.lower().endswith(".png") else "jpg"
            dest = d / "original" / f"{item_id}.{ext}"
            if ext == "png":
                im.save(dest, "PNG")
            else:
                im.save(dest, "JPEG", quality=95)
            raw.unlink()
            item.update(original_url=f"/files/{job_id}/original/{dest.name}", width=im.width, height=im.height)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            log.info("job %s item %s (%s) is not a readable image", job_id, item_id, name)
            item.update(status="failed", error=ERR_NOT_A_PHOTO)
        items.append(item)

    job = {
        "job_id": job_id, "status": "queued",
        "options": {"scale": scale, "faces": faces, "captions": captions},
        "total": len(items),
        "done": sum(1 for it in items if it["status"] in ("done", "failed")),
        "items": items,
    }
    with _lock:
        _jobs[job_id] = job
        _save(job)
    _queue.put(job_id)
    start_worker()
    return get_job(job_id)


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return copy.deepcopy(job) if job else None


def set_caption(job_id: str, item_id: str, caption: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        item = next((it for it in job["items"] if it["id"] == item_id), None) if job else None
        if item is None:
            return None
        item["caption"] = caption
        _save(job)
        return copy.deepcopy(item)


def load_existing() -> int:
    """Reload job.json files after a restart; re-queue unfinished jobs. Returns jobs loaded."""
    if not config.JOBS_DIR.is_dir():
        return 0
    count = 0
    for path in sorted(config.JOBS_DIR.glob("*/job.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            job_id = job["job_id"]
        except (OSError, ValueError, KeyError):
            log.warning("skipping unreadable %s", path)
            continue
        with _lock:
            if job_id in _jobs:
                continue
            _jobs[job_id] = job
            if job["status"] in ("queued", "running"):
                for it in job["items"]:
                    if it["status"] not in ("done", "failed"):
                        it["status"] = "queued"
                job["status"] = "queued"
                _save(job)
                _queue.put(job_id)
        count += 1
    if count:
        start_worker()
    return count


def start_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="revive-worker", daemon=True)
            _worker.start()


# --- worker ------------------------------------------------------------------

def _worker_loop() -> None:
    while True:
        job_id = _queue.get()
        try:
            _run_job(job_id)
        except Exception:
            log.exception("job %s crashed", job_id)
            with _lock:
                job = _jobs.get(job_id)
                if job:
                    job["status"] = "failed"
                    _save(job)
        finally:
            _queue.task_done()


def _run_job(job_id: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
    if job is None:
        return
    opts = job["options"]

    # Steps whose helper isn't installed are skipped rather than failing every photo.
    restore_faces = caption_photo = None
    if opts.get("faces") and is_available("backend.pipeline.faces", "faces_available"):
        restore_faces = optional("backend.pipeline.faces", "restore_faces")
    if opts.get("captions") and is_available("backend.captions.gemma", "gemma_available"):
        caption_photo = optional("backend.captions.gemma", "caption_photo")
    upscaler_ok = upscale_mod.upscaler_available()

    _update(job, status="running")
    d = job_dir(job_id)
    for item in job["items"]:
        if item["status"] in ("done", "failed"):
            continue
        _process_item(job, item, d, opts, restore_faces, caption_photo, upscaler_ok)
        _update(job, done=sum(1 for it in job["items"] if it["status"] in ("done", "failed")))

    all_failed = all(it["status"] == "failed" for it in job["items"])
    _update(job, status="failed" if all_failed else "done")


def _process_item(job, item, d: Path, opts, restore_faces, caption_photo, upscaler_ok) -> None:
    started = time.perf_counter()
    original = d / "original" / item["original_url"].rsplit("/", 1)[-1]
    stage_error = ERR_UNKNOWN
    try:
        src = original
        if restore_faces:
            stage_error = ERR_FACES
            _update(job, item, status="faces")
            faces_out = d / "faces" / f"{item['id']}.png"
            n = restore_faces(src, faces_out)
            _update(job, item, faces_found=int(n))
            src = faces_out

        stage_error = ERR_UPSCALE if upscaler_ok else ERR_UPSCALER_MISSING
        _update(job, item, status="upscaling")
        if not upscaler_ok:
            raise RuntimeError("upscaler not available")
        result = d / "result" / f"{item['id']}.png"
        out_w, out_h = upscale_mod.upscale(src, result, scale=int(opts.get("scale", 4)))
        _update(job, item, out_width=out_w, out_height=out_h,
                result_url=f"/files/{job['job_id']}/result/{result.name}")

        if caption_photo:
            stage_error = ERR_CAPTION
            _update(job, item, status="captioning")
            cap = caption_photo(original)  # P3 makes the <=1024px copy inside caption_photo
            _update(job, item, caption=cap.get("caption"), decade=cap.get("decade"))

        _update(job, item, status="done", seconds=round(time.perf_counter() - started, 1))
    except Exception:
        log.exception("job %s item %s (%s) failed", job["job_id"], item["id"], item["filename"])
        _update(job, item, status="failed", error=stage_error,
                seconds=round(time.perf_counter() - started, 1))
