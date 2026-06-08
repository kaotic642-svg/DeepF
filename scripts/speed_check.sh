#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="/workspace/Deep-Live-Cam"
STREAMING_ROOT="/workspace/streaming"
PROCESSING_LOG="${PROJECT_ROOT}/logs/rtmp_deeplivecam_webui.log"
MEDIAMTX_LOG="${STREAMING_ROOT}/logs/mediamtx.log"

echo "========== DeepLiveCam Speed Check =========="
date
echo

echo "=== Processes ==="
pgrep -af "rtmp_deeplivecam|ffmpeg|mediamtx|uvicorn" || true
echo

echo "=== CPU / MEM ==="
ps ww -eo pid,pcpu,pmem,cmd \
  | grep -E "rtmp_deeplivecam|ffmpeg|mediamtx|uvicorn" \
  | grep -v grep || true
echo

echo "=== GPU ==="
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw \
  --format=csv,noheader,nounits || true
echo

echo "=== Active ffmpeg command ==="
pgrep -af "ffmpeg.*live/processed" || echo "No output ffmpeg process"
echo

echo "=== MediaMTX ports ==="
ss -lntup | grep -E "1935|7860|8890|8889|8189" || true
echo

echo "=== MediaMTX stream status ==="
tail -200 "${MEDIAMTX_LOG}" 2>/dev/null \
  | grep -E "live/test|live/processed|reader is too slow|too many reordered|closed:|publishing|reading" \
  | tail -80 || true
echo

echo "=== Processing FPS lines ==="
tail -120 "${PROCESSING_LOG}" 2>/dev/null \
  | grep -E "frames=|Starting ffmpeg|Applied providers|error|ERROR|Traceback|reader_frames|reconnects" \
  | tail -80 || true
echo

echo "=== Parsed processing metrics ==="
PYTHONPATH="${PROJECT_ROOT}" python - <<'PY'
import re
from pathlib import Path

log_path = Path("/workspace/Deep-Live-Cam/logs/rtmp_deeplivecam_webui.log")
text = log_path.read_text(errors="replace") if log_path.exists() else ""

lines = [line for line in text.splitlines() if "frames=" in line]
last = lines[-1] if lines else ""

def last_float(pattern):
    matches = re.findall(pattern, text)
    return float(matches[-1]) if matches else None

def last_int(pattern):
    matches = re.findall(pattern, text)
    return int(matches[-1]) if matches else None

avg_out_fps = last_float(r"avg_out_fps=([0-9]+(?:\.[0-9]+)?)")
proc_fps = last_float(r"proc_fps=([0-9]+(?:\.[0-9]+)?)")
errors = last_int(r"errors=([0-9]+)")
frames = last_int(r"(?:^|[ ,])frames=([0-9]+)")
processed = last_int(r"processed=([0-9]+)")
reader_frames = last_int(r"reader_frames=([0-9]+)")
reconnects = last_int(r"reconnects=([0-9]+)")

print("last_line:", last or "NO FPS LINES")
print("frames:", frames)
print("processed:", processed)
print("avg_out_fps:", avg_out_fps)
print("proc_fps:", proc_fps)
print("errors:", errors)
print("reader_frames:", reader_frames)
print("reconnects:", reconnects)

print()
print("=== Verdict ===")

fresh_ratio = None
if frames and processed is not None and frames > 0:
    fresh_ratio = processed / frames
    print("fresh_processed_ratio:", round(fresh_ratio, 3))

if avg_out_fps is None or proc_fps is None:
    print("PROBLEM: нет FPS-метрик. Обработка не запущена или лог пустой.")
elif avg_out_fps >= 29.0 and (errors or 0) == 0:
    print("OK: output держит realtime около 30 FPS, серверная очередь не копится.")
    if proc_fps < 29.0:
        print("WARNING: fresh face-swap FPS ниже 30; возможны микрофризы/повтор последнего обработанного кадра.")
else:
    print("PROBLEM: output FPS ниже realtime, задержка может копиться.")

if reader_frames is not None and frames is not None:
    if reader_frames >= frames:
        print("OK: latest-frame reader работает, вход читается достаточно активно.")
    else:
        print("WARNING: reader_frames меньше frames, стоит проверить latest-frame reader.")

if reconnects and reconnects > 0:
    print(f"WARNING: были reconnects={reconnects}, возможны обрывы входного потока.")

if errors and errors > 0:
    print(f"PROBLEM: errors={errors}, нужно смотреть traceback/error строки.")
PY

echo
echo "========== End =========="
