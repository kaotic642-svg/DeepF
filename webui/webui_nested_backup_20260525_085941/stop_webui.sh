#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/app.py" || -f "${SCRIPT_DIR}/../app.py" ]]; then
  PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
elif [[ -d "${DEEPLIVECAM_ROOT:-/workspace/Deep-Live-Cam}" ]]; then
  PROJECT_ROOT="$(cd "${DEEPLIVECAM_ROOT:-/workspace/Deep-Live-Cam}" && pwd)"
else
  echo "[WebUI] ERROR: cannot locate DeepLiveCam project root" >&2
  exit 1
fi

PORT="${WEBUI_PORT:-7860}"
LOG_DIR="${PROJECT_ROOT}/logs"
PID_FILE="${LOG_DIR}/webui.pid"

stop_pid() {
  local pid="$1"
  if [[ -z "${pid}" ]] || ! kill -0 "${pid}" >/dev/null 2>&1; then
    return 0
  fi

  echo "[WebUI] Stopping PID ${pid}..."
  kill "${pid}" >/dev/null 2>&1 || true

  for _ in {1..20}; do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done

  echo "[WebUI] PID ${pid} did not stop gracefully; forcing..."
  kill -9 "${pid}" >/dev/null 2>&1 || true
}

PIDS=""

if [[ -f "${PID_FILE}" ]]; then
  PID_FROM_FILE="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${PID_FROM_FILE}" ]]; then
    PIDS="${PIDS} ${PID_FROM_FILE}"
  fi
fi

if command -v pgrep >/dev/null 2>&1; then
  MATCHED="$(pgrep -f "uvicorn .*((webui\\.app:app)|(app:app)).*--port[ =]${PORT}" || true)"
  if [[ -n "${MATCHED}" ]]; then
    PIDS="${PIDS} ${MATCHED}"
  fi
fi

PIDS="$(printf '%s\n' ${PIDS} 2>/dev/null | awk '!seen[$0]++')"

if [[ -z "${PIDS}" ]]; then
  echo "[WebUI] No WebUI process found."
  rm -f "${PID_FILE}"
  exit 0
fi

for pid in ${PIDS}; do
  if [[ "${pid}" != "$$" ]]; then
    stop_pid "${pid}"
  fi
done

rm -f "${PID_FILE}"

echo "[WebUI] Remaining:"
if command -v pgrep >/dev/null 2>&1; then
  pgrep -af "uvicorn .*((webui\\.app:app)|(app:app)).*--port[ =]${PORT}" || echo "No WebUI process."
else
  echo "Stopped."
fi
