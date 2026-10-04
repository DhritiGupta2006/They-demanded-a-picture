# P1 handoff — server & upscaling (Phases 1–2)

Scope: P1's Phase 1 and Phase 2 work only, per `prompts/00-master-context.md`, `phase-1-kickoff.md` and `phase-2-core-build.md`. Nothing from Phases 3–6 was started.

## What P1 implemented

**Phase 1: backend skeleton**
- `backend/config.py`: paths, the `REVIVE_MOCK` flag, Real-ESRGAN settings, picking the binary for the current OS. Everything can be overridden with env vars (`REVIVE_DATA_DIR`, `REVIVE_BIN_DIR`, `REVIVE_REALESRGAN_BIN`, `REVIVE_MOCK_DELAY`, `REVIVE_GEMMA_MODEL`).
- `backend/jobs.py`: in-memory job store, **one** background worker thread that processes items sequentially, and an atomic `job.json` write after every status change. On startup, saved jobs are reloaded and unfinished ones re-queued. Per-item order is original → faces → upscale → caption (master §7.3). A failing item gets a friendly `error` and the batch carries on.
- `backend/app.py`: every route in master §7.1 (health, create job, poll job, album, PATCH caption, `/files/...`, `/`).
- Mock paths: upscale = Pillow LANCZOS, faces = copy and return 0, captions = a canned sentence. Each mock step sleeps 0.5s.
- `scripts/dev.sh`: mock server with reload on port 8765.

**Phase 2: real upscaling + health**
- `backend/pipeline/upscale.py`: calls `realesrgan-ncnn-vulkan` through `subprocess` with model `realesrgan-x4plus`.
  - 2× = run 4×, then a 50% LANCZOS downscale.
  - Input guard: any side over 2500px is shrunk first (logged).
  - Tile size: `-t 0` first, then one retry with `-t 128`. A run counts as failed on a non-zero exit **or** a missing output file. A timeout (30 min) is not retried.
  - HEIC through `pillow-heif`, plus EXIF rotation with `ImageOps.exif_transpose`.
  - `upscaler_available()`: the binary and model exist, and `-h` prints its usage.
- `GET /api/health` reports the real `upscaler_available()` and calls P3's `faces_available()` / `gemma_available()`. An ImportError or exception counts as `False`.
- `python -m backend.pipeline.try_upscale <files/folders> [--scale 2|4]` prints a timing for each photo.

## Files changed (all new, since the repo had no commits)

| File | Owner | Note |
|---|---|---|
| `backend/__init__.py`, `backend/pipeline/__init__.py`, `backend/captions/__init__.py`, `backend/album/__init__.py` | P1 (Phase 1 task 1) | empty package markers |
| `backend/config.py`, `backend/jobs.py`, `backend/app.py`, `backend/pipeline/upscale.py` | P1 | |
| `backend/pipeline/try_upscale.py` | P1 | Phase 2 CLI |
| `backend/pipeline/faces.py` | **P3** | **placeholder**: mock path only (Phase 1 task 5) |
| `backend/captions/gemma.py` | **P3** | **placeholder**: mock path only (Phase 1 starter prompt) |
| `scripts/dev.sh` | P1 | |
| `tests/conftest.py`, `tests/test_p1_backend.py` | P1 | |
| `requirements.txt` | shared | P1's lines: fastapi, uvicorn, python-multipart, pillow, pillow-heif, pytest, httpx |
| `.gitignore` | **P3** | created early so `data/ samples/ bin/ models/ .venv/` can't be committed (§9). Contents match P3's Phase 1 list, plus `.pytest_cache/` |
| `docs/post-notes.md` | shared | created with P1's entries; P3 owns the format |
| `docs/P1-handoff.md` | P1 | this file |

## Install & run

```bash
# Python 3.11 is the team standard; this was built and tested on 3.13 (3.11 wasn't installed here).
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # macOS/Linux: .venv/bin/python

# Mock server (no models needed): http://localhost:8765
scripts/dev.sh            # Windows: run from Git Bash

# Real upscaler: unzip the realesrgan-ncnn-vulkan release for your OS into bin/
#   https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0  (realesrgan-ncnn-vulkan-20220424-<os>.zip)
#   so you have bin/realesrgan-ncnn-vulkan(.exe) and bin/models/realesrgan-x4plus.{param,bin}
#   macOS: chmod +x bin/realesrgan-ncnn-vulkan && xattr -d com.apple.quarantine bin/realesrgan-ncnn-vulkan
.venv/Scripts/python -m uvicorn backend.app:app --port 8765      # real mode (REVIVE_MOCK unset)
.venv/Scripts/python -m backend.pipeline.try_upscale samples/public/ --scale 4
```

Curl smoke test (mock):
```bash
curl -s localhost:8765/api/health
curl -s -F files=@a.jpg -F files=@b.png -F scale=4 localhost:8765/api/jobs      # -> 201 {"job_id":"..."}
curl -s localhost:8765/api/jobs/<job_id>                                         # poll until "status":"done"
```

## Tests

```bash
.venv/Scripts/python -m pytest tests -q
```
17 tests cover the API end to end in mock mode:
- a bad file next to good ones, 2×/4× sizes, options off, EXIF rotation
- all-failed → job `failed`, 422/404 errors, `/files` restrictions, PATCH caption
- the album placeholder returning 503, restart re-queueing
- the upscaler: input guard, HEIC, tile retry and give-up (subprocess faked), and a real run of the binary (skipped if `bin/` isn't set up)

## Verified

- `pytest`: **17 passed** on Windows 11, Python 3.13 (real-binary test included, not skipped).
- Phase 1 "done when": the curl sequence creates a job with 2 images and polls it to `done` (mock). Result files are served, the album returns 503 (expected), and PATCH works.
- The real Real-ESRGAN binary runs on an Intel UHD 620 iGPU (Vulkan). Timings are below and in `docs/post-notes.md`.

**Real upscale timings** (Intel UHD 620 iGPU, Windows 11; Real-ESRGAN's bundled demo images and resized copies, since `samples/public/` didn't exist yet):

| Input | Scale | Output | Time |
|---|---|---|---|
| 220×220 | 4× | 880×880 | 38.4s |
| 256×256 | 4× | 1024×1024 | 39.4s |
| 800×800 | 4× | 3200×3200 | 198.0s |
| 220×220 | 2× | 440×440 | 23.3s |
| 2800×2100 → guard → 2500×1875 | 4× | — | **timed out after 15 min** (old limit); estimated ~25 min |

That works out to roughly 20s fixed start-up per photo plus about 0.3 MP/min. Because of the last row, the timeout is now 30 min and timeouts are not retried.
A real-mode API job (1 photo, 2×, faces + captions requested) finished `done` in 25.6s, with faces/captions skipped because P3's modules aren't in yet.

## Intentionally mocked / not implemented (other owners)

- **Faces (P3):** `faces.py` is a placeholder. Mock copies the file; real mode raises `NotImplementedError` and `faces_available()` is `False` outside mock.
- **Captions (P3):** `gemma.py` is a placeholder. Mock returns a canned caption; real mode is the same as faces.
- **Album (P2):** `backend/album/export.py` doesn't exist. `GET /api/jobs/{id}/album` returns **503** "The album maker isn't ready yet." until `build_album(job, job_dir) -> Path` lands; after that, nothing in `app.py` needs to change.
- **Frontend (P2):** `/` serves a one-line placeholder until `frontend/index.html` exists, then `frontend/` is mounted at `/` (restart the server once after it's added).
- Not done because it isn't P1's: `CLAUDE.md`, `docs/plan/` copies, `README.md`, `LICENSE`, setup/start scripts, `samples/public/` (all P3).

## Assumptions & known issues

- **Unavailable steps are skipped, not failed.** In real mode, if `faces_available()` / `gemma_available()` is False, `jobs.py` skips that step for the job (`faces_found` / `caption` stay `null`). If the upscaler is missing, each item fails with "The sharpening tool isn't installed yet. Please run the setup again."
- **A caption failure fails the item** (contract: "marks that item failed"). `result_url` is still set when the upscale already finished, so the sharpened photo isn't lost. Phase 3 may want to soften this.
- `faces_found`, `caption` and `decade` are `null` when that option is off.
- Uploads are normalised **in the POST request** into upright `original/<id>.jpg` (or `.png` for PNG input), so `original_url` is valid right away and HEIC shows in browsers. Files that can't be read are marked `failed` at once.
- A job is `failed` only when **every** item failed; otherwise `done`.
- `caption_photo` receives the **original** path; P3 makes the ≤1024px copy inside it, per the P3 Phase 2 spec.
- Mock-mode `*_available()` all return True so P2 can test every toggle.
- The Windows Real-ESRGAN build exits **127** on `-h`, so the health check looks for the usage text instead.
- iGPU speed: a 4× upscale of an input near the 2500px guard takes many minutes on a UHD 620 (see timings). Phase 4 may want a lower `UPSCALE_MAX_INPUT_SIDE` or to default to 2× on weak machines (not changed here; that's Phase 4).
- Python 3.13 was used locally. P3 should check that gfpgan/torch installs on the team's 3.11.

## Where the next developer continues

1. **P3:** replace the real-mode bodies in `backend/pipeline/faces.py` and `backend/captions/gemma.py`, keeping the signatures and mock branches. `jobs.py` and `/api/health` pick them up automatically. Add `samples/public/` and run `try_upscale` on it.
2. **P2:** add `frontend/` and `backend/album/export.py::build_album(job: dict, job_dir: Path) -> Path` (zip). Run `scripts/dev.sh` against mock mode.
3. **Phase 3 (integration):** start in `backend/jobs.py::_run_job` / `_process_item`. That's where step order, skip-vs-fail policy, and per-step timing live. New routes or contract changes go through P1 (master §4).
