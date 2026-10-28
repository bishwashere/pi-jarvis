#!/usr/bin/env bash
# Linux/Pi experimental foreground controller; shares Jarvis's single-instance lock.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${JARVIS_PROJECT_DIR:-$SCRIPT_DIR}" && pwd)"
ENV_FILE="${JARVIS_ENV_FILE:-$PROJECT_DIR/.env}"
names=() values=()
for name in ${!JARVIS_@}; do names+=("$name"); values+=("${!name}"); done
if [[ -f "$ENV_FILE" ]]; then
    set -a
    source "$ENV_FILE"
    set +a
fi
for ((i=0; i<${#names[@]}; i++)); do
    printf -v "${names[$i]}" '%s' "${values[$i]}"
    export "${names[$i]}"
done
VENV_DIR="${JARVIS_VENV_DIR:-$PROJECT_DIR/runtime/venv}"
[[ "$VENV_DIR" == /* ]] || VENV_DIR="$PROJECT_DIR/$VENV_DIR"
cd "$PROJECT_DIR"
export PYTHONUNBUFFERED=1
exec flock -F -n "${JARVIS_LOCK_FILE:-/tmp/jarvis-voice.lock}" "$VENV_DIR/bin/python" "$PROJECT_DIR/hassmic_jarvis.py" "$@"
