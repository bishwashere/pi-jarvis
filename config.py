"""Runtime configuration for both the deployed Pi and local development.

Environment overrides use the ``JARVIS_`` prefix.  Defaults intentionally keep
the deployed Raspberry Pi behaviour, while paths to files that live in this
repository are derived from the checkout location.
"""

import os
import sys
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

# ALSA remains the Raspberry Pi default. Other platforms use PortAudio through
# sounddevice, which selects the operating system's default output device.
PLAYBACK_BACKEND = os.environ.get("JARVIS_PLAYBACK_BACKEND", "auto").lower()
_default_playback_device = (
    "plughw:2,0" if sys.platform.startswith("linux") else "default"
)
PLAYBACK_DEVICE = _audio_device(
    os.environ.get("JARVIS_PLAYBACK_DEVICE", _default_playback_device)
)
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
DAILY_CONTEXT_PATH = _env_path(
    "JARVIS_DAILY_CONTEXT_PATH",
    LOG_DIR / "daily_context.json",
)
COMMAND_SILENCE_SECONDS = 2.0
COMMAND_MIN_RECORD_SECONDS = 0.7
COMMAND_AUDIO_RMS_THRESHOLD = 420
WHISPER_TIMEOUT_SECONDS = 180
QUICK_COMMAND_ENABLED = _env_bool("JARVIS_QUICK_COMMAND_ENABLED", True)
QUICK_COMMAND_PHRASES = [
    phrase.strip()
    for phrase in os.environ.get(
        "JARVIS_QUICK_COMMAND_PHRASES",
        ",".join(
            [
                "yes",
                "yeah",
                "yep",
                "sure",
                "ok",
                "okay",
                "no",
                "nope",
                "stop",
                "cancel",
                "nothing",
                "do nothing",
                "never mind",
                "nevermind",
                "bye",
                "goodbye",
                "weather",
                "weather today",
                "time",
                "what time is it",
            ]
        ),
    ).split(",")
    if phrase.strip()
]


# ---------- Wake word ----------

# For now, we are using Vosk based wake detection.
# Keep longer phrases before shorter words so command cleanup works well.
WAKE_WORDS = [
    "hello jarvis",
    "hey jarvis",
    "hi jarvis",
    "hello computer",
    "hey computer",
    "jarvis",
    "computer",
    "hello",
    "hi",
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
API_CONVERSATION_ID = os.environ.get(
    "JARVIS_API_CONVERSATION_ID",
    "raspberry-pi-jarvis",
)
API_CONTEXT_CONVERSATION_ID = os.environ.get(
    "JARVIS_API_CONTEXT_CONVERSATION_ID",
    f"{API_CONVERSATION_ID}-daily-context",
)

SYSTEM_PROMPT = (
    "You are a voice assistant running through a Raspberry Pi. "
    "Keep replies short and natural. Usually answer in one short phrase or one short sentence. "
    "Expand only when the user asks you to explain or asks for details. "
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

# How long to wait after an answer for a natural follow-up.
FOLLOWUP_SECONDS = 20

# Prevent duplicate wake triggers.
DUPLICATE_WAKE_SECONDS = 3

# If the Pi fails to capture a command after wake, return to wake mode quietly.
COMMAND_RETRY_COUNT = 1

# If the API/server call fails, retry this many times.
API_RETRY_COUNT = 2


# ---------- Local Jarvis command server ----------

COMMAND_SERVER_ENABLED = _env_bool("JARVIS_COMMAND_SERVER_ENABLED", True)
COMMAND_SERVER_HOST = os.environ.get("JARVIS_COMMAND_SERVER_HOST", "127.0.0.1")
COMMAND_SERVER_PORT = int(os.environ.get("JARVIS_COMMAND_SERVER_PORT", "8765"))
COMMAND_SERVER_TOKEN = os.environ.get("JARVIS_COMMAND_SERVER_TOKEN", "").strip()
WELCOME_HOME_COOLDOWN_SECONDS = float(
    os.environ.get("JARVIS_WELCOME_HOME_COOLDOWN_SECONDS", "900")
)
WELCOME_HOME_REPLIES = [
    "Welcome home.",
    "Hey, welcome back.",
    "Good to have you home.",
    "You're home. Welcome back.",
]


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
WAKE_REPLIES = [
    "Hi.",
    "Hello.",
    "Hey.",
    "Hi. How can I help?",
    "Hello. What can I do?",
]
CHECKING_REPLIES = [
    "Let me check.",
    "Checking.",
    "One moment.",
    "Let me look.",
    "I'll check.",
]
CHECKING_REPLY_DELAY_SECONDS = 1.8
STILL_CHECKING_REPLIES = [
    "Still checking.",
    "Almost there.",
    "Still looking.",
    "One more moment.",
    "Working on it.",
]
STILL_CHECKING_REPLY_DELAY_SECONDS = 3.0
STANDBY_REPLIES = [
    "Resting now.",
    "Talk to you later.",
    "I'll be here.",
    "Going quiet.",
    "Sleep mode.",
]
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


# ---------- Daily context bucket ----------

DAILY_CONTEXT_ENABLED = _env_bool("JARVIS_DAILY_CONTEXT_ENABLED", True)
DAILY_CONTEXT_WAKE_REPLY_PROBABILITY = float(
    os.environ.get("JARVIS_DAILY_CONTEXT_WAKE_REPLY_PROBABILITY", "0.35")
)
DAILY_CONTEXT_MIN_UTTERANCES = int(
    os.environ.get("JARVIS_DAILY_CONTEXT_MIN_UTTERANCES", "1")
)
DAILY_CONTEXT_REFRESH_SECONDS = float(
    os.environ.get("JARVIS_DAILY_CONTEXT_REFRESH_SECONDS", "120")
)
DAILY_CONTEXT_MAX_UTTERANCES = int(
    os.environ.get("JARVIS_DAILY_CONTEXT_MAX_UTTERANCES", "40")
)
DAILY_CONTEXT_MAX_SUGGESTIONS = int(
    os.environ.get("JARVIS_DAILY_CONTEXT_MAX_SUGGESTIONS", "8")
)
