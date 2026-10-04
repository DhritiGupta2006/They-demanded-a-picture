"""P2 tests: album export and upload edge cases. Run: python -m pytest tests -q"""
import io
import json
import re
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import app


def _img(size, fmt="JPEG", color="peru") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def _wait(client, job_id, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _run(client, files, **data):
    r = client.post("/api/jobs", files=files, data=data)
    assert r.status_code == 201
    return _wait(client, r.json()["job_id"])


def test_album_contents_and_offline(client):
    job = _run(client, [
        ("files", ("Nani <wedding> & friends.jpg", _img((80, 60)), "image/jpeg")),
        ("files", ("trip/portrait.png", _img((30, 50), "PNG"), "image/png")),
        ("files", ("fake.jpg", b"just some text", "image/jpeg")),
    ], scale="2")
    assert client.patch(f"/api/jobs/{job['job_id']}/items/0001",
                        json={"caption": "Nani <b>& co</b>"}).status_code == 200
    r = client.get(f"/api/jobs/{job['job_id']}/album")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {"album.html", "captions.json"} <= names
    assert sum(n.startswith("photos/") for n in names) == 2   # the corrupt file is left out
    assert sum(n.startswith("originals/") for n in names) == 2
    assert any(n.startswith("photos/0001_Nani") for n in names)

    page = z.read("album.html").decode()
    assert not re.search(r'(?:src|href)=["\']https?://', page) and "cdn" not in page.lower()
    assert "Nani &lt;b&gt;&amp; co&lt;/b&gt;" in page and "<b>& co</b>" not in page   # captions escaped
    assert page.count('class="toggle"') == 2 and "@media print" in page
    for name in re.findall(r'src="([^"]+)"', page):   # every image path resolves inside the zip
        from urllib.parse import unquote
        assert unquote(name) in names

    meta = json.loads(z.read("captions.json"))
    assert meta["photos"][0]["caption"] == "Nani <b>& co</b>" and len(meta["photos"]) == 2
    for n in names:
        if n.startswith("photos/"):
            assert Image.open(io.BytesIO(z.read(n))).size in ((160, 120), (60, 100))


def test_album_with_no_finished_photos_fails_calmly(client):
    job = _run(client, [("files", ("a.txt", b"nope", "image/jpeg"))])
    assert job["status"] == "failed"
    assert client.get(f"/api/jobs/{job['job_id']}/album").status_code == 500   # nothing to put in an album


def test_edge_case_uploads(client):
    big = _img((3000, 2000))
    job = _run(client, [
        ("files", ("tiny.png", _img((1, 1), "PNG"), "image/png")),
        ("files", ("huge.jpg", big, "image/jpeg")),
        ("files", ("portrait.jpg", _img((200, 600)), "image/jpeg")),
        ("files", ("landscape.jpg", _img((600, 200)), "image/jpeg")),
        ("files", ("corrupt.jpg", _img((50, 50))[:100], "image/jpeg")),
        ("files", ("renamed.jpg", b"This is a text file", "image/jpeg")),
    ], scale="2")
    by_name = {it["filename"]: it for it in job["items"]}
    assert job["status"] == "done"
    for name in ("tiny.png", "huge.jpg", "portrait.jpg", "landscape.jpg"):
        assert by_name[name]["status"] == "done", by_name[name]
    assert (by_name["tiny.png"]["out_width"], by_name["tiny.png"]["out_height"]) == (2, 2)
    for name in ("corrupt.jpg", "renamed.jpg"):
        assert by_name[name]["status"] == "failed" and "couldn't be opened" in by_name[name]["error"]
