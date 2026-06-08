#!/usr/bin/env bash
set -e

cd /workspace/Deep-Live-Cam

unset QT_PLUGIN_PATH
unset QT_QPA_PLATFORM_PLUGIN_PATH

export TF_CPP_MIN_LOG_LEVEL=2

echo "[DeepLiveCam] Starting QUALITY mode: face_swapper + GFPGAN face_enhancer"
echo "[DeepLiveCam] Logs: /workspace/Deep-Live-Cam/logs/deeplivecam_gfpgan.log"

xvfb-run -a python run.py \
  --execution-provider cuda \
  --frame-processor face_swapper face_enhancer \
  2>&1 | tee logs/deeplivecam_gfpgan.log
