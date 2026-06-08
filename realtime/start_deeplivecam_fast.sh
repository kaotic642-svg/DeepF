#!/usr/bin/env bash
set -e

cd /workspace/Deep-Live-Cam
export PYTHONPATH=/workspace/Deep-Live-Cam:$PYTHONPATH
mkdir -p logs

echo "[DeepLiveCam RTMP] live/test -> face_swapper -> live/processed"

python realtime/rtmp_deeplivecam.py \
  --source /workspace/Deep-Live-Cam/realtime/source.jpg \
  --input rtmp://127.0.0.1:1935/live/test \
  --output rtmp://127.0.0.1:1935/live/processed \
  --width 1280 \
  --height 720 \
  --fps 30 \
  --bitrate 3000k \
  --every-n 1 \
  2>&1 | tee logs/rtmp_deeplivecam_fast.log
