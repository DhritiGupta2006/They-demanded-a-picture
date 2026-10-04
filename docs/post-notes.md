# Post notes

Running log for the write-up. Everyone appends, one line per entry (master §13):
`[Sun 11:20][P1] what happened → what we did. Numbers if you have them.`

[Sun][P1] Backend skeleton up: FastAPI + one sequential worker thread + job.json after every item status change. Mock job with 2 photos runs start to finish via curl.
[Sun][P1] Real-ESRGAN ncnn-vulkan (20220424 Windows build) runs on an Intel UHD 620 iGPU via Vulkan, no CUDA. Gotcha: `-h` prints usage but exits with code 127, so the health check looks for the usage text instead of a zero exit code.
[Sun][P1] Gotcha: the binary can exit 0 without writing an output file (e.g. GPU out of memory), so we check the output file exists, not just the exit code, before retrying with `-t 128`.
[Sun][P1] Upscale timings, Intel UHD 620 iGPU, realesrgan-x4plus at 4x: 220px → 38s, 256px → 39s, 800x800 → 198s. 2x of 220px (4x then halve) → 23s. That's roughly 20s fixed start-up per photo + ~0.3 megapixels/min.
[Sun][P1] A 2800x2100 scan (shrunk to 2500x1875 by the input guard) at 4x did NOT finish within 15 min on the iGPU, so it timed out. Fixes: timeout raised to 30 min, and a timeout no longer retries with -t 128 (smaller tiles don't make a slow GPU faster, they just double the wait). Open question for Phase 4: lower the 2500px guard or default to 2x on weak laptops.
