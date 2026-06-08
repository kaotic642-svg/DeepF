#!/usr/bin/env bash
set -e

cd /workspace/Deep-Live-Cam

unset QT_PLUGIN_PATH
unset QT_QPA_PLATFORM_PLUGIN_PATH

export TF_CPP_MIN_LOG_LEVEL=2

echo "[DeepLiveCam] Starting with CUDA via xvfb..."
echo "[DeepLiveCam] Logs: /workspace/Deep-Live-Cam/logs/deeplivecam.log"

xvfb-run -a python run.py --execution-provider cuda 2>&1 | tee logs/deeplivecam.log
