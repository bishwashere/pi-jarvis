#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${JARVIS_PROJECT_DIR:-$SCRIPT_DIR}" && pwd)"
ENV_FILE="${JARVIS_ENV_FILE:-$PROJECT_DIR/.env}"
if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi
VENV_DIR="${JARVIS_VENV_DIR:-$PROJECT_DIR/runtime/venv}"
if [[ "$VENV_DIR" != /* ]]; then
    VENV_DIR="$PROJECT_DIR/$VENV_DIR"
fi
LOG_FILE="${JARVIS_LOG_FILE:-$PROJECT_DIR/logs/jarvis_voice.log}"
LOCK_FILE="${JARVIS_LOCK_FILE:-/tmp/jarvis-voice.lock}"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "Jarvis virtual environment not found at $VENV_DIR" >&2
    echo "Run the uv setup documented in README.md first." >&2
    exit 1
fi

cd "$PROJECT_DIR"
mkdir -p "$(dirname "$LOG_FILE")" runtime/cache

export JARVIS_PROJECT_DIR="$PROJECT_DIR"
export PATH="$VENV_DIR/bin:$PATH"
export PYTHONUNBUFFERED=1

if [[ "${JARVIS_FOREGROUND:-0}" == "1" ]]; then
    exec flock -n "$LOCK_FILE" "$VENV_DIR/bin/python" "$PROJECT_DIR/jarvis_voice.py"
fi

exec flock -n "$LOCK_FILE" "$VENV_DIR/bin/python" "$PROJECT_DIR/jarvis_voice.py" >>"$LOG_FILE" 2>&1
