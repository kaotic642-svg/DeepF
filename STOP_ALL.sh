#!/usr/bin/env bash

cd /workspace/Deep-Live-Cam

./webui/stop_webui.sh || true

pkill -f rtmp_deeplivecam.py || true
pkill -f "ffmpeg.*live/processed" || true
pkill -f "/workspace/streaming/mediamtx" || true
pkill -f "./mediamtx" || true

echo "[OK] WebUI, processing and MediaMTX stopped."
