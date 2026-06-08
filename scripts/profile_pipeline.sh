#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="/workspace/Deep-Live-Cam"
OUT_DIR="${PROJECT_ROOT}/logs/profiling"
TS="$(date +%Y%m%d_%H%M%S)"
OUT_LOG="${OUT_DIR}/profile_${TS}.log"
GPU_LOG="${OUT_DIR}/gpu_${TS}.log"
SPY_SVG="${OUT_DIR}/pyspy_${TS}.svg"
SPY_RAW="${OUT_DIR}/pyspy_${TS}.txt"
DURATION="${1:-45}"

mkdir -p "${OUT_DIR}"

exec > >(tee -a "${OUT_LOG}") 2>&1

echo "========== DeepLiveCam Profiling =========="
date
echo "Duration: ${DURATION}s"
echo

cd "${PROJECT_ROOT}"

PID="$(pgrep -f "rtmp_deeplivecam.py" | head -1 || true)"

if [[ -z "${PID}" ]]; then
  echo "[ERROR] rtmp_deeplivecam.py is not running."
  echo "Start Processing in WebUI first."
  exit 1
fi

echo "Processing PID: ${PID}"
echo

echo "=== Current command ==="
ps ww -p "${PID}" -o pid,pcpu,pmem,cmd || true
pgrep -af "ffmpeg.*live/processed" || true
echo

echo "=== Speed check before profiling ==="
./scripts/speed_check.sh || true
echo

echo "=== Installing py-spy if missing ==="
if ! command -v py-spy >/dev/null 2>&1; then
  python -m pip install py-spy
fi

echo
echo "=== GPU monitor started ==="
(
  echo "timestamp,name,gpu_util,mem_used,mem_total,temp,power"
  for i in $(seq 1 "${DURATION}"); do
    printf "%s," "$(date '+%H:%M:%S')"
    nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw \
      --format=csv,noheader,nounits || true
    sleep 1
  done
) > "${GPU_LOG}" &
GPU_MON_PID="$!"

echo "GPU log: ${GPU_LOG}"

echo
echo "=== py-spy dump ==="
py-spy dump --pid "${PID}" --native > "${SPY_RAW}" 2>&1 || true
cat "${SPY_RAW}" | head -120 || true

echo
echo "=== py-spy flamegraph recording ==="
echo "Output: ${SPY_SVG}"

py-spy record \
  --pid "${PID}" \
  --duration "${DURATION}" \
  --rate 100 \
  --native \
  --output "${SPY_SVG}" || true

wait "${GPU_MON_PID}" || true

echo
echo "=== Speed check after profiling ==="
./scripts/speed_check.sh || true

echo
echo "=== Top GPU samples ==="
tail -20 "${GPU_LOG}" || true

echo
echo "========== Result files =========="
ls -lh "${OUT_DIR}" | tail -20

echo
echo "Profile log: ${OUT_LOG}"
echo "GPU log:     ${GPU_LOG}"
echo "PySpy raw:   ${SPY_RAW}"
echo "PySpy SVG:   ${SPY_SVG}"
echo
echo "========== Done =========="
