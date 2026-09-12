#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${JARVIS_PROJECT_DIR:-/home/jarvis/jarvis}"
LOG_FILE="$PROJECT_DIR/logs/jarvis_voice.log"
LOCK_FILE="/tmp/jarvis-voice.lock"

cd "$PROJECT_DIR"
mkdir -p logs runtime/cache

export PATH="$PROJECT_DIR/runtime/venv/bin:$PATH"
export PYTHONUNBUFFERED=1

exec flock -n "$LOCK_FILE" "$PROJECT_DIR/runtime/venv/bin/python" "$PROJECT_DIR/jarvis_voice.py" >>"$LOG_FILE" 2>&1
