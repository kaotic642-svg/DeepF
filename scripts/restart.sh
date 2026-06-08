#!/usr/bin/env bash
set -e

/workspace/Deep-Live-Cam/scripts/stop.sh

sleep 2

/workspace/Deep-Live-Cam/scripts/start_cuda_xvfb.sh
