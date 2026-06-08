#!/usr/bin/env bash
set -e

cd /workspace/Deep-Live-Cam

echo "=== NVIDIA-SMI ==="
nvidia-smi

echo
echo "=== PYTHON / TORCH / ONNX ==="
python - <<'PY'
import torch
import onnxruntime as ort

print("torch:", torch.__version__)
print("cuda available:", torch.cuda.is_available())
print("torch cuda:", torch.version.cuda)
print("gpu:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NO GPU")
print("onnxruntime:", ort.__version__)
print("providers:", ort.get_available_providers())
PY

echo
echo "=== MODELS ==="
ls -lh models
