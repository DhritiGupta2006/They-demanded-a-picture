"""Record a demo of Revive for the DEV post (P3).

Needs the real app running on http://localhost:8765 and Playwright:
    venv/bin/pip install playwright && venv/bin/python -m playwright install chromium
    venv/bin/python scripts/record_demo.py [photo ...]

Writes the raw recording to docs/media/demo-raw.webm and the moment the
waiting part starts and ends to docs/media/demo-marks.json, which
scripts/make_demo_video.sh uses to speed that part up.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "media"
URL = "http://localhost:8765"
SIZE = {"width": 1280, "height": 800}
DEFAULT_PHOTOS = ["wedding-trio-1925.jpg", "children-maple-syrup.jpg", "wedding-party-1920s.jpg"]

# A visible cursor dot, since headless recordings don't draw the mouse.
CURSOR_JS = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;z-index:2147483647;width:22px;height:22px;margin:-11px 0 0 -11px;' +
    'border-radius:50%;background:rgba(255,255,255,.55);border:2px solid rgba(20,12,6,.8);' +
    'box-shadow:0 1px 6px rgba(0,0,0,.4);pointer-events:none;left:-50px;top:-50px;transition:transform .12s';
  document.body.appendChild(c);
  addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  addEventListener('mousedown', () => c.style.transform = 'scale(.75)', true);
  addEventListener('mouseup', () => c.style.transform = '', true);
});
"""


def main(photos: list[Path]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    marks: dict[str, float] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport=SIZE, record_video_dir=str(OUT / "_rec"), record_video_size=SIZE,
                                      accept_downloads=True)
        t0 = time.monotonic()
        mark = lambda name: marks.__setitem__(name, round(time.monotonic() - t0, 2))  # noqa: E731
        context.add_init_script(CURSOR_JS)
        page = context.new_page()
        mouse = page.mouse

        def glide_to(locator, steps=25):
            box = locator.bounding_box()
            mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=steps)

        def click(locator, pause=0.8):
            glide_to(locator)
            page.wait_for_timeout(250)
            locator.click()
            page.wait_for_timeout(int(pause * 1000))

        page.goto(URL)
        page.wait_for_load_state("networkidle")
        mouse.move(640, 300)
        page.wait_for_timeout(2000)  # let the viewer read the hero

        glide_to(page.locator("#btn-photos"))
        page.wait_for_timeout(400)
        page.locator("#input-photos").set_input_files([str(p) for p in photos])
        page.wait_for_selector("#options:not([hidden])")
        page.wait_for_timeout(1500)

        click(page.locator("label:has(input[name=scale][value='2'])"), pause=1.0)
        page.locator("#start-row").scroll_into_view_if_needed()
        click(page.locator("#btn-start"), pause=0.5)

        mark("wait_start")
        page.wait_for_selector("#step-results:not([hidden])", timeout=30 * 60 * 1000)
        mark("wait_end")
        page.wait_for_timeout(2500)  # show the results grid with captions

        click(page.locator("#results-grid .card .open").first, pause=1.2)
        slider = page.locator("#v-stage .ba")
        slider.wait_for()
        page.wait_for_timeout(800)
        box = slider.bounding_box()
        y = box["y"] + box["height"] * 0.55
        x = lambda f: box["x"] + box["width"] * f  # noqa: E731
        mouse.move(x(0.5), y, steps=15)
        mouse.down()
        for target in (0.12, 0.88, 0.3, 0.7, 0.5):
            mouse.move(x(target), y, steps=60)
            page.wait_for_timeout(450)
        mouse.up()
        page.wait_for_timeout(1500)

        click(page.locator("#v-close"), pause=1.0)
        glide_to(page.locator("#btn-album"))
        page.wait_for_timeout(300)
        with page.expect_download() as dl:
            page.locator("#btn-album").click()
        dl.value.save_as(OUT / "_rec" / "album.zip")
        page.wait_for_timeout(2500)
        mark("end")

        video = page.video
        context.close()
        browser.close()
        shutil.move(video.path(), OUT / "demo-raw.webm")

    shutil.rmtree(OUT / "_rec", ignore_errors=True)
    (OUT / "demo-marks.json").write_text(json.dumps(marks, indent=1))
    print(json.dumps(marks))


if __name__ == "__main__":
    args = sys.argv[1:]
    sample = ROOT / "samples" / "public"
    main([Path(a) for a in args] if args else [sample / n for n in DEFAULT_PHOTOS])
