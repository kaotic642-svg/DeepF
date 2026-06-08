#!/usr/bin/env bash
set -Eeuo pipefail

cd /workspace/Deep-Live-Cam

echo "[Deps] Installing system dependencies..."

apt update

apt install -y \
  git wget curl ffmpeg \
  build-essential cmake pkg-config \
  python3-dev python3.12-dev \
  xvfb xauth \
  libegl1 libgl1 libgles2 libopengl0 \
  libxkbcommon0 libxkbcommon-x11-0 \
  libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 \
  libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
  libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 \
  libxcb-sync1 libxcb-xinput0 libxcb1 \
  libdbus-1-3 libfontconfig1 libfreetype6 \
  libx11-6 libx11-xcb1 libxext6 libxrender1 \
  libsm6 libice6

echo "[Deps] Installing Python dependencies..."

python -m pip install --upgrade pip setuptools wheel
python -m pip install "Cython<3"

python -m pip install opencv-python-headless numpy
python -m pip install insightface==0.7.3
python -m pip install PySide6

python -m pip uninstall -y onnxruntime onnxruntime-gpu || true
python -m pip install onnxruntime-gpu==1.21.0

python -m pip install fastapi uvicorn python-multipart jinja2

echo "[Deps] Checking runtime..."

PYTHONPATH=/workspace/Deep-Live-Cam python - <<'PY'
import cv2
import insightface
import onnxruntime as ort
import torch
from PySide6.QtCore import Qt
from modules.processors.frame import face_swapper

print("cv2:", cv2.__version__)
print("insightface:", insightface.__version__)
print("onnxruntime:", ort.__version__)
print("providers:", ort.get_available_providers())
print("torch:", torch.__version__)
print("cuda:", torch.cuda.is_available())
print("DeepLiveCam modules: OK")
PY

echo "[Deps] Done."
