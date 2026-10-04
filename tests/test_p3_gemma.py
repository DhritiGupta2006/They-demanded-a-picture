"""P3: Gemma captions in real mode, with Ollama faked by monkeypatching urlopen."""
import io
import json

import pytest
from PIL import Image

from backend import config
from backend.captions import gemma


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_urlopen(payloads, calls=None):
    """Returns each payload in turn (a dict is JSON-encoded, an Exception is raised)."""
    it = iter(payloads)

    def _urlopen(req, timeout=None):
        if calls is not None:
            calls.append(req)
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(json.dumps(item).encode())

    return _urlopen


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(config, "MOCK", False)
    monkeypatch.setattr(config, "GEMMA_MODEL", "gemma4:e4b-it-qat")
    monkeypatch.delenv("OLLAMA_HOST", raising=False)


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "old.jpg"
    Image.new("RGB", (2000, 1500), (120, 100, 80)).save(p)
    return p


def test_available_matches_model_name(real_mode, monkeypatch):
    tags = {"models": [{"name": "gemma4:e4b-it-qat"}, {"name": "qwen3:14b"}]}
    monkeypatch.setattr(gemma.urllib.request, "urlopen", fake_urlopen([tags]))
    assert gemma.gemma_available() is True


def test_available_treats_latest_as_bare_name(real_mode, monkeypatch):
    monkeypatch.setattr(config, "GEMMA_MODEL", "gemma4")
    tags = {"models": [{"name": "gemma4:latest"}]}
    monkeypatch.setattr(gemma.urllib.request, "urlopen", fake_urlopen([tags]))
    assert gemma.gemma_available() is True


def test_unavailable_when_model_missing_or_server_down(real_mode, monkeypatch):
    monkeypatch.setattr(gemma.urllib.request, "urlopen", fake_urlopen([{"models": [{"name": "gemma4:e2b-it-qat"}]}]))
    assert gemma.gemma_available() is False
    monkeypatch.setattr(gemma.urllib.request, "urlopen", fake_urlopen([ConnectionRefusedError()]))
    assert gemma.gemma_available() is False


@pytest.mark.parametrize("raw, expected", [
    ("1970s", "1970s"), ("1970's", "1970s"), ("the 70s", "1970s"), ("70s", "1970s"),
    ("1974", "1970s"), ("1900s", "1900s"), ("unknown", None), ("", None), (None, None), ("old", None),
])
def test_decade_normalisation(raw, expected):
    assert gemma.normalize_decade(raw) == expected


def test_caption_happy_path(real_mode, monkeypatch, photo):
    calls = []
    answer = {"response": json.dumps({"caption": '"Two children sit on the porch steps. They smile."', "decade": "the 50's"})}
    monkeypatch.setattr(gemma.urllib.request, "urlopen", fake_urlopen([answer], calls))
    assert gemma.caption_photo(photo) == {"caption": "Two children sit on the porch steps.", "decade": "1950s"}
    body = json.loads(calls[0].data)
    assert calls[0].full_url == "http://127.0.0.1:11434/api/generate"
    assert body["model"] == "gemma4:e4b-it-qat" and body["stream"] is False and body["think"] is False
    assert body["format"]["required"] == ["caption", "decade"]
    sent = Image.open(io.BytesIO(__import__("base64").b64decode(body["images"][0])))
    assert max(sent.size) == config.CAPTION_MAX_SIDE


def test_bad_json_retries_once_then_raises(real_mode, monkeypatch, photo):
    calls = []
    bad = {"response": "not json at all"}
    monkeypatch.setattr(gemma.urllib.request, "urlopen", fake_urlopen([bad, bad], calls))
    with pytest.raises(RuntimeError, match="Couldn't write a caption"):
        gemma.caption_photo(photo)
    assert len(calls) == 2


def test_server_down_raises_friendly_error(real_mode, monkeypatch, photo):
    monkeypatch.setattr(gemma.urllib.request, "urlopen", fake_urlopen([ConnectionRefusedError()]))
    with pytest.raises(RuntimeError, match="Couldn't write a caption"):
        gemma.caption_photo(photo)


def test_refuses_non_local_ollama_host(real_mode, monkeypatch, photo):
    monkeypatch.setenv("OLLAMA_HOST", "example.com:11434")
    monkeypatch.setattr(gemma.urllib.request, "urlopen", fake_urlopen([]))  # must never be called
    assert gemma.gemma_available() is False
    with pytest.raises(RuntimeError, match="Couldn't write a caption"):
        gemma.caption_photo(photo)


def test_mock_path_unchanged(monkeypatch, photo):
    monkeypatch.setattr(config, "MOCK", True)
    assert gemma.gemma_available() is True
    assert gemma.caption_photo(photo)["decade"] == "1980s"
