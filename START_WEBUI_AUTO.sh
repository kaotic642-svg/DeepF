#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="/workspace/Deep-Live-Cam"

cd "${PROJECT_ROOT}"

mkdir -p logs

export WEBUI_PASSWORD="${WEBUI_PASSWORD:-123456789}"
export STREAMING_ROOT="${STREAMING_ROOT:-${PROJECT_ROOT}/streaming}"

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-4}"
export ORT_NUM_THREADS="${ORT_NUM_THREADS:-4}"
export DLC_FLUSH_EVERY="${DLC_FLUSH_EVERY:-3}"

chmod +x scripts/*.sh 2>/dev/null || true
chmod +x webui/*.sh 2>/dev/null || true
chmod +x streaming/*.sh 2>/dev/null || true
chmod +x streaming/mediamtx 2>/dev/null || true

if [[ -x "${PROJECT_ROOT}/scripts/install_runtime_deps.sh" ]]; then
  echo "[AUTO] Installing/checking runtime dependencies..."
  "${PROJECT_ROOT}/scripts/install_runtime_deps.sh" || true
fi

echo "[AUTO] Starting WebUI..."
exec "${PROJECT_ROOT}/webui/start_webui.sh"
