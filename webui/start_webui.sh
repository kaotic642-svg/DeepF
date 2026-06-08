#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

APP_MODULE="${WEBUI_APP_MODULE:-webui.app:app}"
APP_FILE="${SCRIPT_DIR}/app.py"

HOST="${WEBUI_HOST:-0.0.0.0}"
PORT="${WEBUI_PORT:-7860}"
PYTHON_BIN="${PYTHON_BIN:-python}"
STREAMING_ROOT="${STREAMING_ROOT:-${PROJECT_ROOT}/streaming}"

LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/webui.log"
PID_FILE="${LOG_DIR}/webui.pid"

if [[ -z "${WEBUI_PASSWORD:-}" ]]; then
  echo "[WebUI] ERROR: WEBUI_PASSWORD is not set." >&2
  echo "[WebUI] Example: WEBUI_PASSWORD='123456789' ./webui/start_webui.sh" >&2
  exit 1
fi

if [[ ! -f "${APP_FILE}" ]]; then
  echo "[WebUI] ERROR: app.py not found: ${APP_FILE}" >&2
  exit 1
fi

mkdir -p "${LOG_DIR}"

export DEEPLIVECAM_ROOT="${PROJECT_ROOT}"
export STREAMING_ROOT
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"
export WEBUI_PASSWORD

# Limit CPU thread pools used by OpenCV / NumPy / ONNXRuntime.
# This reduces CPU overload while keeping realtime 30 FPS stable.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-4}"
export ORT_NUM_THREADS="${ORT_NUM_THREADS:-4}"

# Flush ffmpeg pipe every N frames.
# 1 = lowest buffering, higher CPU/write cost.
# 3 = safer low-latency optimization for 30 FPS.
export DLC_FLUSH_EVERY="${DLC_FLUSH_EVERY:-3}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "[WebUI] ERROR: python executable not found: ${PYTHON_BIN}" >&2
  exit 1
fi

if [[ -f "${PID_FILE}" ]]; then
  OLD_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" >/dev/null 2>&1; then
    echo "[WebUI] Already running. PID: ${OLD_PID}"
    echo "[WebUI] URL: http://127.0.0.1:${PORT}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

if command -v ss >/dev/null 2>&1 && ss -lnt "sport = :${PORT}" | grep -q ":${PORT}"; then
  echo "[WebUI] ERROR: port ${PORT} is already in use." >&2
  ss -lntp "sport = :${PORT}" || true
  exit 1
fi

echo "[WebUI] Project root: ${PROJECT_ROOT}"
echo "[WebUI] App module: ${APP_MODULE}"
echo "[WebUI] Host/port: ${HOST}:${PORT}"
echo "[WebUI] Log file: ${LOG_FILE}"
echo "[WebUI] Login: admin"
echo "[WebUI] Password: value from WEBUI_PASSWORD"

cd "${PROJECT_ROOT}"
"${PYTHON_BIN}" -m py_compile "${APP_FILE}"

{
  echo
  echo "========== WebUI start $(date '+%Y-%m-%d %H:%M:%S') =========="
  echo "[WebUI] Project root: ${PROJECT_ROOT}"
  echo "[WebUI] App module: ${APP_MODULE}"
  echo "[WebUI] Host/port: ${HOST}:${PORT}"
} >> "${LOG_FILE}"

nohup "${PYTHON_BIN}" -m uvicorn "${APP_MODULE}" \
  --host "${HOST}" \
  --port "${PORT}" \
  >> "${LOG_FILE}" 2>&1 &

WEBUI_PID="$!"
echo "${WEBUI_PID}" > "${PID_FILE}"

sleep 2

if ! kill -0 "${WEBUI_PID}" >/dev/null 2>&1; then
  echo "[WebUI] ERROR: process exited during startup." >&2
  rm -f "${PID_FILE}"
  echo "[WebUI] Last log:"
  tail -80 "${LOG_FILE}" || true
  exit 1
fi

echo "[WebUI] Started. PID: ${WEBUI_PID}"
echo "[WebUI] URL: http://127.0.0.1:${PORT}"

if command -v curl >/dev/null 2>&1; then
  if curl -fsS --max-time 5 -u "admin:${WEBUI_PASSWORD}" "http://127.0.0.1:${PORT}/api/health" >/dev/null; then
    echo "[WebUI] API check: OK"
  else
    echo "[WebUI] API check: not ready yet; see ${LOG_FILE}"
  fi
fi

echo "[WebUI] Last log:"
tail -40 "${LOG_FILE}" || true
