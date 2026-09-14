"""Runtime configuration for both the deployed Pi and local development.

Environment overrides use the ``JARVIS_`` prefix.  Defaults intentionally keep
the deployed Raspberry Pi behaviour, while paths to files that live in this
repository are derived from the checkout location.
"""

import os
from pathlib import Path


def _env_path(name: str, default: Path) -> str:
    """Return an absolute path, resolving relative overrides from PROJECT_DIR."""
    raw_value = os.environ.get(name)
    path = Path(raw_value).expanduser() if raw_value else default
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return str(path.resolve())


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value, got {raw_value!r}")


def _audio_device(value: str):
    """Allow PortAudio device indexes as well as device names in env values."""
    stripped = value.strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    return stripped


PROJECT_DIR = Path(
    os.environ.get("JARVIS_PROJECT_DIR", Path(__file__).resolve().parent)
).expanduser().resolve()
RUNTIME_DIR = PROJECT_DIR / "runtime"
ASSETS_DIR = RUNTIME_DIR / "assets"
LOG_DIR = PROJECT_DIR / "logs"


# ---------- Audio ----------

# Python/sounddevice input device. Prefer a stable name/hint over a numeric
# PortAudio index because indexes can change after reboot.
AUDIO_DEVICE = _audio_device(os.environ.get("JARVIS_AUDIO_DEVICE", "default"))

_audio_fallbacks = os.environ.get("JARVIS_AUDIO_DEVICE_FALLBACKS")
if _audio_fallbacks:
    AUDIO_DEVICE_FALLBACKS = [
        _audio_device(value)
        for value in _audio_fallbacks.split(",")
        if value.strip()
    ]
else:
    AUDIO_DEVICE_FALLBACKS = [
        "pulse",
        "P10S: USB Audio",
        "USB Audio",
        0,
    ]

# ALSA playback device for your USB speaker.
PLAYBACK_DEVICE = os.environ.get("JARVIS_PLAYBACK_DEVICE", "plughw:2,0")
CONFIGURE_VOLUME = _env_bool("JARVIS_CONFIGURE_VOLUME", True)
VOLUME_CARD = os.environ.get("JARVIS_VOLUME_CARD", "2")
VOLUME_CONTROL = os.environ.get("JARVIS_VOLUME_CONTROL", "PCM")
VOLUME_LEVEL = os.environ.get("JARVIS_VOLUME_LEVEL", "85%")

SAMPLE_RATE = 16000
VOSK_MODEL_PATH = _env_path(
    "JARVIS_VOSK_MODEL_PATH",
    ASSETS_DIR / "vosk-model-small-en-us-0.15",
)


# ---------- Speech to text ----------

# Vosk is still used for wake detection. This controls command transcription.
# Use "vosk" to go back to the original streaming recognizer.
COMMAND_STT_ENGINE = os.environ.get("JARVIS_COMMAND_STT_ENGINE", "whisper")

# Local whisper.cpp test setup.
WHISPER_CPP_DIR = Path(
    os.environ.get("JARVIS_WHISPER_CPP_DIR", PROJECT_DIR.parent / "whisper.cpp")
).expanduser()
if not WHISPER_CPP_DIR.is_absolute():
    WHISPER_CPP_DIR = PROJECT_DIR / WHISPER_CPP_DIR
WHISPER_CPP_DIR = WHISPER_CPP_DIR.resolve()
WHISPER_CPP_BINARY = _env_path(
    "JARVIS_WHISPER_CPP_BINARY",
    WHISPER_CPP_DIR / "build/bin/whisper-cli",
)
WHISPER_MODEL_PATH = _env_path(
    "JARVIS_WHISPER_MODEL_PATH",
    WHISPER_CPP_DIR / "models/ggml-tiny.en.bin",
)
WHISPER_THREADS = 1
COMMAND_RECORDING_PATH = _env_path(
    "JARVIS_COMMAND_RECORDING_PATH",
    LOG_DIR / "command.wav",
)
COMMAND_SILENCE_SECONDS = 1.2
COMMAND_MIN_RECORD_SECONDS = 0.7
COMMAND_AUDIO_RMS_THRESHOLD = 350
WHISPER_TIMEOUT_SECONDS = 180


# ---------- Wake word ----------

# For now, we are using Vosk based wake detection.
# Keep longer phrases before shorter words so command cleanup works well.
WAKE_WORDS = [
    "hello jarvis",
    "hey jarvis",
    "hello computer",
    "hey computer",
    "jarvis",
    "computer",
    "hello",
]

# 0 = only wake on exact phrases in WAKE_WORDS.
# 100 = wake on any recognized speech.
# Values in between lower the similarity needed to treat speech as a wake phrase.
LENIENT_WAKE_LEVEL = 70


# ---------- Local AI API ----------

API_BASE_URL = os.environ.get(
    "JARVIS_API_BASE_URL",
    "http://192.168.1.82:1235/v1/agents/jarvis",
).rstrip("/")
API_URL = os.environ.get(
    "JARVIS_API_URL",
    f"{API_BASE_URL}/chat/completions",
)
API_HEALTH_URL = os.environ.get(
    "JARVIS_API_HEALTH_URL",
    f"{API_BASE_URL}/health",
)
API_MODEL = os.environ.get("JARVIS_API_MODEL", "api-assistant")

SYSTEM_PROMPT = (
    "You are a voice assistant running through a Raspberry Pi. "
    "Keep replies short and natural. Usually answer in one or two sentences. "
    "Do not use markdown. "
    "If you need the user to clarify, if you think speech recognition misunderstood them, "
    "or if the task is incomplete, return JSON exactly like this: "
    "{\"reply\":\"your spoken reply\", \"continue_listening\":true}. "
    "If the task is complete, you may return normal plain text. "
    "When returning JSON, do not wrap it in markdown or code blocks."
)


# ---------- Timing ----------

# How long to listen for the first command after wake.
MAX_COMMAND_SECONDS = 60

# How long to listen after an answer for natural follow-up.
FOLLOWUP_SECONDS = 4

# Prevent duplicate wake triggers.
DUPLICATE_WAKE_SECONDS = 3

# If the Pi fails to capture a command after wake, return to wake mode quietly.
COMMAND_RETRY_COUNT = 1

# If the API/server call fails, retry this many times.
API_RETRY_COUNT = 2


# ---------- Voice / TTS ----------

# Piper American female voice.
PIPER_BINARY = os.environ.get("JARVIS_PIPER_BINARY", "piper")
PIPER_MODEL_PATH = _env_path(
    "JARVIS_PIPER_MODEL_PATH",
    ASSETS_DIR / "piper/en_US-amy-medium.onnx",
)

# Used only if you use file based playback.
REPLY_WAV_PATH = _env_path("JARVIS_REPLY_WAV_PATH", LOG_DIR / "reply.wav")

# Startup / assistant phrases.
HEALTH_OK_REPLY = "Jarvis agent is online."
HEALTH_ERROR_REPLY = "Jarvis agent health check failed."
WAKE_REPLY = "Hi. How can I help?"
API_RETRY_REPLY = "One second. I am trying again."
API_ERROR_REPLY = "I could not reach Pasture."
GENERIC_ERROR_REPLY = "Something went wrong."
EMPTY_RESPONSE_REPLY = "I have no response."


# ---------- Response cleanup ----------

# Limit text passed to TTS so long replies do not take forever.
MAX_TTS_CHARS = 700


# ---------- Conversation behavior ----------

# If the server returns plain text, this controls whether the Pi should
# automatically keep listening after every answer.
#
# False = after answer, listen only for FOLLOWUP_SECONDS, then return to wake mode.
# True  = after every answer, keep listening like an active conversation.
CONTINUE_LISTENING_DEFAULT = False
