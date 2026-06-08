#!/usr/bin/env bash
set -e

cd /workspace/Deep-Live-Cam
mkdir -p logs

echo "[Passthrough] OBS live/test -> Python -> live/processed"

python realtime/rtmp_passthrough.py \
  --input rtmp://127.0.0.1:1935/live/test \
  --output rtmp://127.0.0.1:1935/live/processed \
  --width 1280 \
  --height 720 \
  --fps 30 \
  --bitrate 3000k \
  2>&1 | tee logs/rtmp_passthrough.log
