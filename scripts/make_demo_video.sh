#!/usr/bin/env bash
# Turn the raw demo recording into docs/media/demo.mp4 (<60s) and demo.gif (800px, <10MB).
# Run after scripts/record_demo.py. The waiting part (between the marks in
# demo-marks.json) is sped up so the whole video fits in TARGET seconds.
set -euo pipefail
cd "$(dirname "$0")/.."
M=docs/media
RAW=$M/demo-raw.webm
TARGET=${TARGET:-55}

read -r A B END < <(python3 -c "import json;m=json.load(open('$M/demo-marks.json'));print(m['wait_start'],m['wait_end'],m['end'])")
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$RAW")
# Playwright starts recording slightly before our t0; trust the file's real length for the tail.
END=$(python3 -c "print(max($END, $DUR))")
WAIT=$(python3 -c "print($B - $A)")
# Leave about 6s of on-screen time for the waiting part, or whatever's left of TARGET.
FAST=$(python3 -c "rest=$TARGET-($A+($END-$B)); print(max(2.0, min(6.0, rest)))")
SPEED=$(python3 -c "print(max(1.0, $WAIT / $FAST))")
echo "intro ${A}s, wait ${WAIT}s -> ${FAST}s (x${SPEED}), outro $(python3 -c "print(round($END-$B,1))")s"

ffmpeg -v error -y -i "$RAW" -filter_complex "
  [0:v]trim=0:$A,setpts=PTS-STARTPTS[a];
  [0:v]trim=$A:$B,setpts=(PTS-STARTPTS)/$SPEED[b];
  [0:v]trim=$B,setpts=PTS-STARTPTS[c];
  [a][b][c]concat=n=3:v=1,fps=30,format=yuv420p[v]" \
  -map "[v]" -c:v libx264 -crf 22 -preset slow -movflags +faststart -an "$M/demo.mp4"

ffmpeg -v error -y -i "$M/demo.mp4" -vf "fps=12,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" "$M/demo.gif"

ls -la "$M/demo.mp4" "$M/demo.gif"
ffprobe -v error -show_entries format=duration -of csv=p=0 "$M/demo.mp4"
