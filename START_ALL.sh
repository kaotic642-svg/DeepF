#!/usr/bin/env bash
set -e

cd /workspace/Deep-Live-Cam

export DEEPLIVECAM_ROOT=/workspace/Deep-Live-Cam
export STREAMING_ROOT=/workspace/streaming
export WEBUI_PASSWORD="${WEBUI_PASSWORD:-123456789}"
export PYTHONPATH=/workspace/Deep-Live-Cam:$PYTHONPATH

echo "[1/2] Starting WebUI..."
./webui/start_webui.sh

echo
echo "[OK] Open WebUI on RunPod HTTP port 7860"
echo "Login: admin"
echo "Password: $WEBUI_PASSWORD"
