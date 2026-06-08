#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

mkdir -p logs

MEDIAMTX_VERSION="${MEDIAMTX_VERSION:-v1.18.2}"
MEDIAMTX_ARCHIVE="mediamtx_${MEDIAMTX_VERSION}_linux_amd64.tar.gz"
MEDIAMTX_URL="https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/${MEDIAMTX_ARCHIVE}"

if [[ ! -x "${SCRIPT_DIR}/mediamtx" ]]; then
  echo "[MediaMTX] mediamtx binary not found, downloading ${MEDIAMTX_VERSION}..."
  apt-get update
  apt-get install -y curl ca-certificates tar
  curl -L "${MEDIAMTX_URL}" -o /tmp/mediamtx.tar.gz
  tar -xzf /tmp/mediamtx.tar.gz -C "${SCRIPT_DIR}" mediamtx
  chmod +x "${SCRIPT_DIR}/mediamtx"
fi

echo "[MediaMTX] Stopping previous process if exists..."
pkill -f "${SCRIPT_DIR}/mediamtx" 2>/dev/null || true

echo "[MediaMTX] Starting RTMP server on internal port 1935..."

nohup "${SCRIPT_DIR}/mediamtx" "${SCRIPT_DIR}/mediamtx.yml" \
  > "${SCRIPT_DIR}/logs/mediamtx.log" 2>&1 &

echo $! > "${SCRIPT_DIR}/logs/mediamtx.pid"

sleep 1

echo
echo "[MediaMTX] Process:"
ps aux | grep -E "${SCRIPT_DIR}/mediamtx|mediamtx.yml" | grep -v grep || true

echo
echo "[MediaMTX] Listening ports:"
ss -lntup | grep ':1935' || true

echo
echo "[MediaMTX] Last logs:"
tail -30 "${SCRIPT_DIR}/logs/mediamtx.log" || true
