"""Revive HTTP API (P1). Routes: master §7.1.

Run (mock):  scripts/dev.sh   or   REVIVE_MOCK=1 uvicorn backend.app:app --port 8765
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import config, jobs
from backend.pipeline.upscale import upscaler_available

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("revive.app")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.JOBS_DIR.mkdir(parents=True, exist_ok=True)
    n = jobs.load_existing()
    jobs.start_worker()
    log.info("Revive ready on http://localhost:%d (mock=%s, %d saved jobs)", config.PORT, config.MOCK, n)
    yield


app = FastAPI(title="Revive", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    return {
        "upscaler": upscaler_available(),
        "faces": jobs.is_available("backend.pipeline.faces", "faces_available"),
        "gemma": jobs.is_available("backend.captions.gemma", "gemma_available"),
        "mock": config.MOCK,
    }


@app.post("/api/jobs", status_code=201)
def create_job(
    files: list[UploadFile] = File(...),
    scale: int = Form(4),
    faces: bool = Form(True),
    captions: bool = Form(True),
) -> dict:
    if scale not in (2, 4):
        raise HTTPException(422, "Sharpening can be 2x or 4x.")
    uploads = [(f.filename, f.file.read()) for f in files if f.filename]
    if not uploads:
        raise HTTPException(400, "Please add at least one photo.")
    job = jobs.create_job(uploads, scale=scale, faces=faces, captions=captions)
    return {"job_id": job["job_id"]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "We couldn't find that batch of photos.")
    return job


@app.get("/api/jobs/{job_id}/album")
def get_album(job_id: str):
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "We couldn't find that batch of photos.")
    if job["status"] not in ("done", "failed"):
        raise HTTPException(409, "The album will be ready when all photos are finished.")
    # backend/album/export.py is owned by P2; until it lands this route answers 503.
    build_album = jobs.optional("backend.album.export", "build_album")
    if build_album is None:
        raise HTTPException(503, "The album maker isn't ready yet.")
    try:
        zip_path = build_album(job, jobs.job_dir(job_id))
    except Exception:
        log.exception("album export failed for job %s", job_id)
        raise HTTPException(500, "We couldn't make the album. Please try again.")
    return FileResponse(zip_path, media_type="application/zip", filename=f"revive-album-{job_id}.zip")


class CaptionPatch(BaseModel):
    caption: str


@app.patch("/api/jobs/{job_id}/items/{item_id}")
def patch_item(job_id: str, item_id: str, body: CaptionPatch) -> dict:
    item = jobs.set_caption(job_id, item_id, body.caption.strip())
    if item is None:
        raise HTTPException(404, "We couldn't find that photo.")
    return item


@app.get("/files/{job_id}/{kind}/{filename}")
def get_file(job_id: str, kind: str, filename: str):
    if kind not in ("original", "result") or jobs.get_job(job_id) is None:
        raise HTTPException(404, "Not found")
    base = (config.JOBS_DIR / job_id / kind).resolve()
    path = (base / filename).resolve()
    if path.parent != base or not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path)


# Frontend (owned by P2) at "/". Registered last so /api and /files win.
if (config.FRONTEND_DIR / "index.html").is_file():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/", response_class=HTMLResponse)
    def frontend_placeholder() -> str:
        return "<h1>Revive</h1><p>The page isn't built yet (frontend/index.html). The API is running.</p>"
