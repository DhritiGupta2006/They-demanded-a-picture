# P2 handoff: frontend & album (Phases 1–4 code work)

Scope: P2's code tasks from phases 1–4. Phase 5 (final demo video, hero GIF, final before/after pairs, repo polish) and Phase 6 (DEV media upload) are recording and publishing work done by hand, so they were not started.

## What P2 added

| File | What |
|---|---|
| `frontend/index.html`, `styles.css`, `app.js` | The whole UI. No framework, no build step. Served at `/` by `app.py` (restart the server once after adding `frontend/`). |
| `backend/album/export.py`, `album_template.html` | `build_album(job, job_dir) -> Path` writes `data/jobs/<id>/album.zip`. `app.py`'s album route picks it up with no changes. |
| `tests/test_p2_album.py` | Album contents and offline check, plus the upload edge cases. |
| `docs/media/readme/01…05-*.png` | The five README screenshots (1280×800 where noted below). |

## Phase 1–2: UI
- Header with "Your photos stay on this computer." Drop zone with files **and folders** (`webkitGetAsEntry` recursive walk, `<input webkitdirectory>` fallback). Non-photos are skipped with a gentle note.
- Preview strip with count and remove-one / remove-all. Options: Make sharper 2×/4×, Fix faces, Write captions.
- Progress: overall bar, per-item stage in friend language (Fixing faces / Making sharper / Writing a caption), failed items show the job's `error` text.
- Results grid with caption and decade. Full-screen viewer with the **before/after slider** (pointer + touch via pointer events, ←/→/Home/End/PageUp/PageDown on the slider, `role="slider"`), prev/next, Esc to close, focus trap. Captions are editable (PATCH on pause or blur).
- Health banner: reads `/api/health`, shows a calm note and disables the matching toggle (and Start, if the upscaler is down).
- Download album button → `/api/jobs/{id}/album`. It's greyed out if no photo finished.
- Dark mode (`prefers-color-scheme`), visible focus styles, reduced-motion respected.

## Phase 3: album and real speeds
- `album.html` is self-contained (inline CSS/JS, relative image paths, no CDN). It has a title, date, caption + decade per photo, a Show-the-original toggle, and print CSS (one photo + caption per page, checked as 3 pages for 3 photos). `photos/0001_<name>.png`, `originals/…`, `captions.json` are alongside. All text is HTML-escaped. Items with no restored file (failed) are left out; with none finished, `build_album` raises `ValueError` and the route returns its friendly 500.
- Animated "working" state (spinner, dots, shimmering bar), "About N minutes left" from the average `seconds` of finished items, and reconnect via `#job=<id>` (reload or reopen mid-job resumes; an unknown id returns to the start screen with a message).

## Tested
- `pytest tests -q`: **19 passed, 1 skipped** (the skip is P1's real-binary test; it skips when `bin/` is absent).
- Browser (Edge via Playwright, mock server): file chooser, folder chooser, skip non-photo, remove, start, progress, reload mid-job, results, album download, slider drag, keyboard, touch drag at 400px, caption edit, new batch, unknown job id, no horizontal scroll at 400px, health banner on a server with no tools, dark mode, album opened from `file://` with every request local, print layout.
- Edge uploads through the API (mock): 1×1 PNG, 3000×2000 JPEG, portrait, landscape, truncated JPEG, `.txt` renamed `.jpg`. Good ones finish; the last two fail with the friendly "couldn't be opened" message and the batch carries on. **No backend bugs found for P1.**
- **Not done:** the real-model run on 15 public photos, and the Wi-Fi-off test of the album on a second machine. The album was only checked with local-only requests. All screenshots came from mock mode, so before/after look nearly the same. Re-shoot slider screenshots (`04`, `05`) with real mode before the post.
- Test photos: `samples/public/` didn't exist and downloads were blocked here, so synthetic sepia "photos" made with Pillow were used (`samples/p2-synthetic/`, gitignored). Three junk HTML files from a failed download are in `samples/public/` (gitignored). They are safe to delete.

## Notes for other owners
- **P1:** I updated `tests/test_p1_backend.py::test_album_placeholder_until_p2` to `test_album_route_serves_zip`, since the album now exists. No change to `app.py`, `jobs.py` or `config.py`.
- **P1 (Phase 4 idea):** a caption failure fails the whole item, so the UI lists it under "couldn't be finished" even though `result_url` exists. The UI still shows such a photo in the results grid, since the sharpened file is there.
- **P3:** README steps can use `docs/media/readme/01-start.png` (empty), `02-ready.png` (photos chosen), `03-progress.png`, `04-results.png`, `05-before-after.png`.
