#!/usr/bin/env bash

echo "[DeepLiveCam] Stopping..."
pkill -f "python run.py" || true
pkill -f "xvfb-run" || true
echo "[DeepLiveCam] Stopped."

echo
echo "Remaining processes:"
ps aux | grep -i "run.py\|xvfb" | grep -v grep || true
