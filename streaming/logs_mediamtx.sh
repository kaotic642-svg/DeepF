#!/usr/bin/env bash
tail -f "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/logs/mediamtx.log"
