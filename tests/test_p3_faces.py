"""P3: GFPGAN face restoration — availability and the mock path (no model needed)."""
from PIL import Image

from backend import config
from backend.pipeline import faces


def test_unavailable_when_weights_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MOCK", False)
    missing = {tmp_path / "GFPGANv1.4.pth": "https://example.invalid/x"}
    monkeypatch.setattr(faces, "WEIGHTS", missing)
    imported = []
    monkeypatch.setattr(faces, "_import_gfpgan", lambda: imported.append(1))
    assert faces.faces_available() is False
    assert imported == []  # cheap: doesn't even try to import torch/gfpgan


def test_unavailable_when_gfpgan_import_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MOCK", False)
    w = tmp_path / "w.pth"
    w.write_bytes(b"x")
    monkeypatch.setattr(faces, "WEIGHTS", {w: "https://example.invalid/x"})

    def boom():
        raise ImportError("no gfpgan")

    monkeypatch.setattr(faces, "_import_gfpgan", boom)
    assert faces.faces_available() is False


def test_mock_path_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MOCK", True)
    src, dst = tmp_path / "a.jpg", tmp_path / "out" / "a.jpg"
    Image.new("RGB", (64, 64), (200, 10, 10)).save(src)
    assert faces.faces_available() is True
    assert faces.restore_faces(src, dst) == 0
    assert dst.read_bytes() == src.read_bytes()


def test_real_mode_failure_is_friendly(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MOCK", False)
    bad = tmp_path / "not-a-photo.jpg"
    bad.write_text("hello")
    try:
        faces.restore_faces(bad, tmp_path / "out.png")
    except RuntimeError as e:
        assert str(e) == "Couldn't fix the faces in this photo."
    else:
        raise AssertionError("expected RuntimeError")
