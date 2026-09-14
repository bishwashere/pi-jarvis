#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Local defaults avoid Raspberry Pi-specific Whisper and ALSA settings. Every
# value remains overridable by the caller.
export JARVIS_PROJECT_DIR="${JARVIS_PROJECT_DIR:-$SCRIPT_DIR}"
export JARVIS_COMMAND_STT_ENGINE="${JARVIS_COMMAND_STT_ENGINE:-vosk}"
export JARVIS_PLAYBACK_DEVICE="${JARVIS_PLAYBACK_DEVICE:-default}"
export JARVIS_CONFIGURE_VOLUME="${JARVIS_CONFIGURE_VOLUME:-0}"
export JARVIS_FOREGROUND="${JARVIS_FOREGROUND:-1}"

exec "$SCRIPT_DIR/run_jarvis.sh"
