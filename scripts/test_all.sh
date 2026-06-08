#!/usr/bin/env bash

set -u

cd /workspace/Deep-Live-Cam
mkdir -p logs

echo "======================================"
echo "DeepLiveCam scripts test"
echo "Date: $(date)"
echo "Path: $(pwd)"
echo "======================================"
echo

echo "=== 1. List scripts ==="
ls -lah scripts
echo

echo "=== 2. Test check_gpu.sh ==="
/workspace/Deep-Live-Cam/scripts/check_gpu.sh
CHECK_GPU_STATUS=$?
echo "[check_gpu.sh exit code]: $CHECK_GPU_STATUS"
echo

echo "=== 3. Test start_cuda_xvfb.sh for 20 seconds ==="
timeout 20s /workspace/Deep-Live-Cam/scripts/start_cuda_xvfb.sh
START_DEFAULT_STATUS=$?
echo "[start_cuda_xvfb.sh exit code]: $START_DEFAULT_STATUS"
echo "Note: exit code 124 means timeout stopped the script, this is OK for launch test."
echo

echo "=== 4. Stop after default launch test ==="
/workspace/Deep-Live-Cam/scripts/stop.sh
echo

echo "=== 5. Test start_fast_cuda_xvfb.sh for 20 seconds ==="
timeout 20s /workspace/Deep-Live-Cam/scripts/start_fast_cuda_xvfb.sh
START_FAST_STATUS=$?
echo "[start_fast_cuda_xvfb.sh exit code]: $START_FAST_STATUS"
echo "Note: exit code 124 means timeout stopped the script, this is OK for launch test."
echo

echo "=== 6. Stop after fast launch test ==="
/workspace/Deep-Live-Cam/scripts/stop.sh
echo

echo "=== 7. Test start_gfpgan_cuda_xvfb.sh for 30 seconds ==="
timeout 30s /workspace/Deep-Live-Cam/scripts/start_gfpgan_cuda_xvfb.sh
START_GFPGAN_STATUS=$?
echo "[start_gfpgan_cuda_xvfb.sh exit code]: $START_GFPGAN_STATUS"
echo "Note: exit code 124 means timeout stopped the script, this is OK for launch test."
echo

echo "=== 8. Stop after GFPGAN launch test ==="
/workspace/Deep-Live-Cam/scripts/stop.sh
echo

echo "=== 9. Check remaining processes ==="
ps aux | grep -i "run.py\|xvfb" | grep -v grep || echo "No DeepLiveCam/Xvfb processes found."
echo

echo "=== 10. Logs summary ==="
echo "--- logs directory ---"
ls -lh logs || true
echo

echo "--- last lines: deeplivecam.log ---"
tail -60 logs/deeplivecam.log 2>/dev/null || echo "No logs/deeplivecam.log"
echo

echo "--- last lines: deeplivecam_fast.log ---"
tail -60 logs/deeplivecam_fast.log 2>/dev/null || echo "No logs/deeplivecam_fast.log"
echo

echo "--- last lines: deeplivecam_gfpgan.log ---"
tail -60 logs/deeplivecam_gfpgan.log 2>/dev/null || echo "No logs/deeplivecam_gfpgan.log"
echo

echo "======================================"
echo "TEST RESULT SUMMARY"
echo "======================================"
echo "check_gpu.sh: $CHECK_GPU_STATUS"
echo "start_cuda_xvfb.sh: $START_DEFAULT_STATUS"
echo "start_fast_cuda_xvfb.sh: $START_FAST_STATUS"
echo "start_gfpgan_cuda_xvfb.sh: $START_GFPGAN_STATUS"
echo

echo "Expected:"
echo "- check_gpu.sh should be 0"
echo "- start scripts may be 124 because timeout stopped them"
echo "- camera warnings /dev/video0 are expected on RunPod"
echo "- CUDAExecutionProvider should be visible"
echo "- no libEGL/xcb/PySide6 fatal error should appear"
echo "======================================"
