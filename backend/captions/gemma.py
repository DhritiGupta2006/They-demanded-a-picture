"""Gemma captions via a local Ollama server (P3).

Each photo gets one warm sentence and a decade guess from a Gemma vision
model running on this computer. We only ever talk to Ollama on localhost,
so photos never leave the machine (master §9).
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageOps

from backend import config

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # HEIC just won't open; everything else still works
    pass

log = logging.getLogger(__name__)

FRIENDLY_ERROR = "Couldn't write a caption for this photo."
TAGS_TIMEOUT = 2
GENERATE_TIMEOUT = 300  # the first call loads the model into memory
MAX_CAPTION_CHARS = 200
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}

PROMPT = """You are helping a family label their old photos for an album.

Look at the photo and reply with JSON containing:
- "caption": ONE warm, plain-English sentence (at most 25 words) describing what you can actually see: who is there, what they are doing, the setting, the occasion if it is clear (a wedding, a birthday, a school photo), and the mood. Write it the way a kind relative would label an album page, not like a security camera.
- "decade": your best guess of when the photo was taken, written like "1970s". Look closely at the clothing, hairstyles and the photo itself: sepia or brown-toned studio portraits with stiff poses usually mean 1880s-1920s; sharp black-and-white snapshots 1930s-1950s; square prints and warm faded colour 1960s-1970s; bright colour with a date stamp 1980s-1990s. If you can't tell, write "unknown".

Rules for the caption:
- Never invent names, relationships (mother, grandfather, couple...) or places you can't see written in the photo. Say "a woman", "two men", "a family".
- Don't start with "This image shows", "This photo shows" or "The image". Start with what is in it.
- Describe; don't judge the photo's quality or mention that it is old or faded."""

SCHEMA = {
    "type": "object",
    "properties": {"caption": {"type": "string"}, "decade": {"type": "string"}},
    "required": ["caption", "decade"],
}


def _base_url() -> str:
    host = os.environ.get("OLLAMA_HOST", "").strip() or "http://127.0.0.1:11434"
    if "://" not in host:
        host = "http://" + host
    hostname = urlsplit(host).hostname or ""
    if hostname in ("0.0.0.0", ""):  # "listen everywhere" setting; connect locally
        host = host.replace("0.0.0.0", "127.0.0.1", 1)
    elif hostname not in LOCAL_HOSTS:
        raise RuntimeError(f"OLLAMA_HOST={host!r} is not localhost; refusing to send photos off this computer")
    return host.rstrip("/")


def _same_model(a: str, b: str) -> bool:
    def norm(name: str) -> str:
        name = name.strip().lower()
        return name if ":" in name else name + ":latest"

    return norm(a) == norm(b)


def gemma_available() -> bool:
    if config.MOCK:
        return True
    try:
        with urllib.request.urlopen(_base_url() + "/api/tags", timeout=TAGS_TIMEOUT) as resp:
            models = json.load(resp).get("models", [])
        return any(_same_model(m.get("name", "") or m.get("model", ""), config.GEMMA_MODEL) for m in models)
    except Exception:
        return False


def _photo_b64(src: Path) -> str:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((config.CAPTION_MAX_SIDE, config.CAPTION_MAX_SIDE), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _generate(image_b64: str) -> str:
    body = {
        "model": config.GEMMA_MODEL,
        "prompt": PROMPT,
        "images": [image_b64],
        "stream": False,
        "think": False,  # gemma4 is a thinking model; we want a fast, direct answer
        "keep_alive": "15m",
        "format": SCHEMA,
        "options": {"temperature": 0.2},
    }
    req = urllib.request.Request(
        _base_url() + "/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=GENERATE_TIMEOUT) as resp:
        return json.load(resp).get("response", "")


def clean_caption(text: str) -> str:
    text = " ".join(str(text).split()).strip().strip("\"'“”‘’").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    if m:
        text = m.group(1)
    if len(text) > MAX_CAPTION_CHARS:
        text = text[:MAX_CAPTION_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def normalize_decade(value) -> str | None:
    """'1970s', "1970's", 'the 70s', '70s', '1974' -> '1970s'. Anything else -> None."""
    if not isinstance(value, str):
        return None
    s = value.strip().lower().replace("’", "'")
    m = re.search(r"\b(18|19|20)(\d)\d\s*'?s?\b", s)
    if m:
        return f"{m.group(1)}{m.group(2)}0s"
    m = re.search(r"(?:^|\s|')(\d)0\s*'?s\b", s)  # "70s", "'70s", "the 70's" -> assume 1900s
    if m:
        return f"19{m.group(1)}0s"
    return None


def _parse(raw: str) -> dict:
    data = json.loads(raw)
    caption = clean_caption(data.get("caption", ""))
    if not caption:
        raise ValueError("empty caption")
    return {"caption": caption, "decade": normalize_decade(data.get("decade"))}


def caption_photo(src: Path) -> dict:
    """{"caption": str, "decade": str | None}. Raises on failure."""
    if config.MOCK:
        time.sleep(config.MOCK_STEP_SECONDS)
        return {"caption": "A family gathers together, smiling for the camera.", "decade": "1980s"}

    try:
        image_b64 = _photo_b64(Path(src))
    except Exception:
        log.exception("caption: couldn't open %s", src)
        raise RuntimeError(FRIENDLY_ERROR)

    last_error: Exception | None = None
    for attempt in (1, 2):  # one retry for bad JSON
        try:
            return _parse(_generate(image_b64))
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            last_error = e
            log.warning("caption: bad model output for %s (attempt %d): %s", src, attempt, e)
        except Exception as e:  # server down, model missing, timeout, non-local host
            log.error("caption: Ollama request failed for %s: %s", src, e)
            raise RuntimeError(FRIENDLY_ERROR) from e
    log.error("caption: giving up on %s: %s", src, last_error)
    raise RuntimeError(FRIENDLY_ERROR)
