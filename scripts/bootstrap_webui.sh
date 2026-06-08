#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="/workspace/Deep-Live-Cam"
STREAMING_ROOT="/workspace/streaming"
LOG_DIR="${PROJECT_ROOT}/logs"
BOOT_LOG="${LOG_DIR}/bootstrap_webui.log"

mkdir -p "${LOG_DIR}"

exec > >(tee -a "${BOOT_LOG}") 2>&1

echo
echo "========== Bootstrap start $(date '+%Y-%m-%d %H:%M:%S') =========="

cd "${PROJECT_ROOT}"

export DEEPLIVECAM_ROOT="${PROJECT_ROOT}"
export STREAMING_ROOT="${STREAMING_ROOT}"
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
export WEBUI_PASSWORD="${WEBUI_PASSWORD:-123456789}"

# Limit CPU thread pools used by OpenCV / NumPy / ONNXRuntime.
# This reduces CPU overload while keeping realtime 30 FPS stable.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-4}"
export ORT_NUM_THREADS="${ORT_NUM_THREADS:-4}"

echo "[Bootstrap] Project root: ${PROJECT_ROOT}"
echo "[Bootstrap] Streaming root: ${STREAMING_ROOT}"
echo "[Bootstrap] WebUI password: value from WEBUI_PASSWORD"

echo "[Bootstrap] Checking Python dependencies..."

if PYTHONPATH="${PROJECT_ROOT}" python - <<'PY'
import cv2
import insightface
import onnxruntime as ort
import torch
import fastapi
import uvicorn
import multipart
import jinja2
from PySide6.QtCore import Qt
from modules.processors.frame import face_swapper

providers = ort.get_available_providers()
assert "CUDAExecutionProvider" in providers, providers
assert torch.cuda.is_available(), "torch cuda is not available"

print("Runtime check: OK")
print("providers:", providers)
print("gpu:", torch.cuda.get_device_name(0))
PY
then
  echo "[Bootstrap] Dependencies are OK."
else
  echo "[Bootstrap] Dependencies are missing or broken. Installing..."
  "${PROJECT_ROOT}/scripts/install_runtime_deps.sh"
fi

echo "[Bootstrap] Stopping stale WebUI processes..."

pkill -9 -f "uvicorn.*webui.app:app" || true
pkill -9 -f "uvicorn.*app:app" || true
rm -f "${PROJECT_ROOT}/logs/webui.pid"

echo "[Bootstrap] Starting WebUI..."

"${PROJECT_ROOT}/webui/start_webui.sh"

echo "[Bootstrap] WebUI status:"
pgrep -af "uvicorn.*webui.app:app" || true

echo "[Bootstrap] Health check:"
curl -fsS --max-time 10 -u "admin:${WEBUI_PASSWORD}" "http://127.0.0.1:7860/api/health" || true

echo
echo "[Bootstrap] Done."
echo "Open RunPod HTTP service on port 7860."
echo "Login: admin"
echo "Password: ${WEBUI_PASSWORD}"
