"""Album export (P2). Contract: master §7.3 `build_album(job, job_dir) -> Path`.

Builds data/jobs/<id>/album.zip containing a self-contained album.html (inline CSS/JS,
relative image paths, no CDN), photos/ (restored), originals/ and captions.json.
"""
from __future__ import annotations

import html
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from urllib.parse import quote

TEMPLATE = Path(__file__).with_name("album_template.html")
ALBUM_TITLE = "Family Album"


def _safe_stem(filename: str) -> str:
    stem = Path(filename.replace("\\", "/").rsplit("/", 1)[-1]).stem
    stem = re.sub(r"[^\w\-. ]+", "_", stem, flags=re.UNICODE).strip(" ._")
    return stem[:60] or "photo"


def _item_files(item: dict, job_dir: Path) -> tuple[Path, Path | None] | None:
    """(restored, original) paths on disk, or None if the item has no restored photo."""
    if not item.get("result_url"):
        return None
    restored = job_dir / "result" / item["result_url"].rsplit("/", 1)[-1]
    if not restored.is_file():
        return None
    original = None
    if item.get("original_url"):
        candidate = job_dir / "original" / item["original_url"].rsplit("/", 1)[-1]
        if candidate.is_file():
            original = candidate
    return restored, original


def _figure(entry: dict) -> str:
    e = {k: html.escape(str(v), quote=True) if v is not None else "" for k, v in entry.items()}
    caption = f'<p class="cap">{e["caption"]}</p>' if entry["caption"] else ""
    decade = f'<p class="dec">{e["decade"]}</p>' if entry["decade"] else ""
    after_src = quote(entry["photo"])
    before_src = quote(entry["original"]) if entry["original"] else ""
    before_img = (f'<img class="before" src="{before_src}" alt="Original photo" loading="lazy">'
                  if before_src else "")
    toggle = (f'<button type="button" class="toggle" aria-pressed="false">Show the original</button>'
              if before_src else "")
    alt = e["caption"] or e["filename"]
    return (
        f'<figure class="photo">'
        f'<div class="frame"><img class="after" src="{after_src}" alt="{alt}" loading="lazy">{before_img}</div>'
        f'<figcaption>{caption}{decade}<p class="fn">{e["filename"]}</p>{toggle}</figcaption>'
        f'</figure>'
    )


def build_album(job: dict, job_dir: Path) -> Path:
    job_dir = Path(job_dir)
    entries: list[dict] = []
    sources: list[tuple[Path, str]] = []
    for item in job.get("items", []):
        found = _item_files(item, job_dir)
        if found is None:
            continue
        restored, original = found
        base = f"{item['id']}_{_safe_stem(item.get('filename') or item['id'])}"
        photo = f"photos/{base}{restored.suffix.lower()}"
        sources.append((restored, photo))
        orig_name = None
        if original is not None:
            orig_name = f"originals/{base}{original.suffix.lower()}"
            sources.append((original, orig_name))
        entries.append({
            "id": item["id"], "filename": item.get("filename") or item["id"],
            "photo": photo, "original": orig_name,
            "caption": item.get("caption") or None, "decade": item.get("decade") or None,
            "width": item.get("width"), "height": item.get("height"),
            "out_width": item.get("out_width"), "out_height": item.get("out_height"),
        })
    if not entries:
        raise ValueError("No finished photos to put in an album.")

    today = date.today()
    page = (TEMPLATE.read_text(encoding="utf-8")
            .replace("{{TITLE}}", html.escape(ALBUM_TITLE))
            .replace("{{DATE}}", today.strftime("%d %B %Y").lstrip("0"))
            .replace("{{COUNT}}", f"{len(entries)} photo{'s' if len(entries) != 1 else ''}")
            .replace("{{PHOTOS}}", "\n".join(_figure(e) for e in entries)))

    captions = {"title": ALBUM_TITLE, "generated": today.isoformat(), "photos": entries}

    out = job_dir / "album.zip"
    tmp = job_dir / "album.zip.tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:  # photos are already compressed
        zf.writestr("album.html", page, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("captions.json", json.dumps(captions, indent=2, ensure_ascii=False),
                    compress_type=zipfile.ZIP_DEFLATED)
        for path, arcname in sources:
            zf.write(path, arcname)
    tmp.replace(out)
    return out
