#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/logs/mediamtx.pid"

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    echo "[MediaMTX] Stopping PID ${PID}"
    kill "${PID}" || true
  fi
  rm -f "${PID_FILE}"
fi

pkill -f "${SCRIPT_DIR}/mediamtx" 2>/dev/null || true

echo "[MediaMTX] Stopped"
