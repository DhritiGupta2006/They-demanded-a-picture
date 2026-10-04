"""P1 backend tests: API, job runner, and upscaler. Run: python -m pytest tests -q"""
import io
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import config, jobs
from backend.app import app
from backend.pipeline import upscale as up


def _img_bytes(size=(64, 48), fmt="JPEG", exif_orientation=None) -> bytes:
    im = Image.new("RGB", size, "sienna")
    buf = io.BytesIO()
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        im.save(buf, fmt, exif=exif.tobytes())
    else:
        im.save(buf, fmt)
    return buf.getvalue()


def _wait(client, job_id, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --- API --------------------------------------------------------------------

def test_health_mock(client):
    assert client.get("/api/health").json() == {"upscaler": True, "faces": True, "gemma": True, "mock": True}


def test_job_end_to_end_with_bad_file(client):
    files = [
        ("files", ("holiday/a.jpg", _img_bytes((64, 48)), "image/jpeg")),
        ("files", ("b.png", _img_bytes((30, 40), "PNG"), "image/png")),
        ("files", ("notes.txt", b"not a photo", "text/plain")),
    ]
    r = client.post("/api/jobs", files=files, data={"scale": "4"})
    assert r.status_code == 201
    job = _wait(client, r.json()["job_id"])

    assert job["status"] == "done" and job["total"] == 3 and job["done"] == 3
    a, b, bad = job["items"]
    assert a["filename"] == "a.jpg" and a["status"] == "done"
    assert (a["out_width"], a["out_height"]) == (256, 192)
    assert a["faces_found"] == 0 and a["caption"] and a["decade"] == "1980s"
    assert a["seconds"] is not None and a["error"] is None
    assert b["original_url"].endswith("/original/0002.png") and (b["out_width"], b["out_height"]) == (120, 160)
    assert bad["status"] == "failed" and bad["error"] == jobs.ERR_NOT_A_PHOTO and bad["result_url"] is None

    for url in (a["original_url"], a["result_url"]):
        assert client.get(url).status_code == 200
    on_disk = json.loads((config.JOBS_DIR / job["job_id"] / "job.json").read_text())
    assert on_disk == job


def test_scale_2_and_options_off(client):
    r = client.post("/api/jobs", files=[("files", ("x.jpg", _img_bytes((50, 20)), "image/jpeg"))],
                    data={"scale": "2", "faces": "false", "captions": "false"})
    job = _wait(client, r.json()["job_id"])
    it = job["items"][0]
    assert job["options"] == {"scale": 2, "faces": False, "captions": False}
    assert (it["out_width"], it["out_height"]) == (100, 40)
    assert it["faces_found"] is None and it["caption"] is None


def test_exif_rotation_applied(client):
    # Orientation 6 = stored sideways; the upright photo is 48 wide, 64 tall.
    r = client.post("/api/jobs", files=[("files", ("scan.jpg", _img_bytes((64, 48), exif_orientation=6), "image/jpeg"))])
    it = _wait(client, r.json()["job_id"])["items"][0]
    assert (it["width"], it["height"]) == (48, 64)


def test_all_items_failed_marks_job_failed(client):
    r = client.post("/api/jobs", files=[("files", ("x.jpg", b"garbage", "image/jpeg"))])
    assert _wait(client, r.json()["job_id"])["status"] == "failed"


def test_bad_requests(client):
    assert client.post("/api/jobs", files=[("files", ("x.jpg", _img_bytes(), "image/jpeg"))],
                       data={"scale": "3"}).status_code == 422
    assert client.post("/api/jobs").status_code == 422
    assert client.get("/api/jobs/nope").status_code == 404


def test_files_route_is_restricted(client):
    r = client.post("/api/jobs", files=[("files", ("x.jpg", _img_bytes(), "image/jpeg"))])
    job_id = r.json()["job_id"]
    _wait(client, job_id)
    assert client.get(f"/files/{job_id}/faces/0001.png").status_code == 404  # only original|result
    assert client.get(f"/files/{job_id}/original/..%2Fjob.json").status_code == 404
    assert client.get(f"/files/{job_id}/result/9999.png").status_code == 404


def test_patch_caption(client):
    r = client.post("/api/jobs", files=[("files", ("x.jpg", _img_bytes(), "image/jpeg"))])
    job_id = r.json()["job_id"]
    _wait(client, job_id)
    r = client.patch(f"/api/jobs/{job_id}/items/0001", json={"caption": " Nani's wedding "})
    assert r.status_code == 200 and r.json()["caption"] == "Nani's wedding"
    assert client.get(f"/api/jobs/{job_id}").json()["items"][0]["caption"] == "Nani's wedding"
    assert client.patch(f"/api/jobs/{job_id}/items/0099", json={"caption": "x"}).status_code == 404


def test_album_route_serves_zip(client):
    r = client.post("/api/jobs", files=[("files", ("x.jpg", _img_bytes(), "image/jpeg"))])
    job_id = r.json()["job_id"]
    _wait(client, job_id)
    r = client.get(f"/api/jobs/{job_id}/album")  # backend/album/export.py (P2) is in
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"


def test_restart_requeues_unfinished_job(client):
    job_id = "abc123"
    d = config.JOBS_DIR / job_id
    (d / "original").mkdir(parents=True)
    (d / "original" / "0001.jpg").write_bytes(_img_bytes((10, 10)))
    item = {"id": "0001", "filename": "x.jpg", "status": "upscaling", "original_url": f"/files/{job_id}/original/0001.jpg",
            "result_url": None, "width": 10, "height": 10, "out_width": None, "out_height": None,
            "faces_found": None, "caption": None, "decade": None, "seconds": None, "error": None}
    job = {"job_id": job_id, "status": "running", "options": {"scale": 2, "faces": False, "captions": False},
           "total": 1, "done": 0, "items": [item]}
    (d / "job.json").write_text(json.dumps(job))
    assert jobs.load_existing() == 1
    done = _wait(client, job_id)
    assert done["status"] == "done" and done["items"][0]["out_width"] == 20


# --- upscaler ----------------------------------------------------------------

def test_input_guard_shrinks_big_images(tmp_path):
    src = tmp_path / "big.jpg"
    Image.new("RGB", (3000, 1500)).save(src)
    assert up.upscale(src, tmp_path / "out.png", scale=2) == (5000, 2500)


def test_bad_scale_raises(tmp_path):
    src = tmp_path / "a.png"
    Image.new("RGB", (4, 4)).save(src)
    with pytest.raises(ValueError):
        up.upscale(src, tmp_path / "o.png", scale=3)


def test_heic_input(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    src = tmp_path / "phone.heic"
    try:
        pillow_heif.from_pillow(Image.new("RGB", (40, 30), "teal")).save(src)
    except Exception as e:  # encoder missing in this wheel
        pytest.skip(f"HEIC encoding unavailable: {e}")
    assert up.upscale(src, tmp_path / "o.png", scale=4) == (160, 120)


def test_real_path_retries_with_small_tiles(tmp_path, monkeypatch):
    fake_exe = tmp_path / config.REALESRGAN_EXE_NAME
    fake_exe.write_bytes(b"")
    monkeypatch.setenv("REVIVE_REALESRGAN_BIN", str(fake_exe))
    monkeypatch.setattr(config, "MOCK", False)
    tiles = []

    def fake_run(cmd, **kw):
        tile = int(cmd[cmd.index("-t") + 1])
        tiles.append(tile)
        if tile == 0:  # simulate integrated-GPU out of memory: exits 0, writes nothing
            return subprocess.CompletedProcess(cmd, 0, "", "vkAllocateMemory failed")
        inp, out = cmd[cmd.index("-i") + 1], cmd[cmd.index("-o") + 1]
        w, h = Image.open(inp).size
        Image.new("RGB", (w * 4, h * 4)).save(out)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(up.subprocess, "run", fake_run)
    src = tmp_path / "a.jpg"
    Image.new("RGB", (30, 20)).save(src)
    assert up.upscale(src, tmp_path / "o.png", scale=2) == (60, 40)
    assert tiles == [0, config.UPSCALE_RETRY_TILE]
    assert Image.open(tmp_path / "o.png").size == (60, 40)


def test_real_path_raises_after_retry(tmp_path, monkeypatch):
    fake_exe = tmp_path / config.REALESRGAN_EXE_NAME
    fake_exe.write_bytes(b"")
    monkeypatch.setenv("REVIVE_REALESRGAN_BIN", str(fake_exe))
    monkeypatch.setattr(config, "MOCK", False)
    monkeypatch.setattr(up.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    src = tmp_path / "a.jpg"
    Image.new("RGB", (8, 8)).save(src)
    with pytest.raises(RuntimeError):
        up.upscale(src, tmp_path / "o.png")


def test_real_path_timeout_is_not_retried(tmp_path, monkeypatch):
    fake_exe = tmp_path / config.REALESRGAN_EXE_NAME
    fake_exe.write_bytes(b"")
    monkeypatch.setenv("REVIVE_REALESRGAN_BIN", str(fake_exe))
    monkeypatch.setattr(config, "MOCK", False)
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(up.subprocess, "run", fake_run)
    src = tmp_path / "a.jpg"
    Image.new("RGB", (8, 8)).save(src)
    with pytest.raises(subprocess.TimeoutExpired):
        up.upscale(src, tmp_path / "o.png")
    assert len(calls) == 1


def test_real_binary_if_installed(tmp_path, monkeypatch):
    """Runs the actual realesrgan-ncnn-vulkan binary from bin/ (skipped if not set up)."""
    monkeypatch.setattr(config, "MOCK", False)
    if not up.upscaler_available():
        pytest.skip("realesrgan-ncnn-vulkan not installed in bin/")
    src = tmp_path / "a.jpg"
    Image.new("RGB", (32, 24), "sienna").save(src)
    assert up.upscale(src, tmp_path / "x2.png", scale=2) == (64, 48)
    assert Image.open(tmp_path / "x2.png").size == (64, 48)
