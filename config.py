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
    return str(path.absolute())


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


_default_project_dir = Path(__file__).resolve().parent
PROJECT_DIR = Path(
    os.environ.get("JARVIS_PROJECT_DIR", _default_project_dir)
).expanduser()
if not PROJECT_DIR.is_absolute():
    PROJECT_DIR = _default_project_dir / PROJECT_DIR
PROJECT_DIR = PROJECT_DIR.absolute()
RUNTIME_DIR = PROJECT_DIR / "runtime"
ASSETS_DIR = RUNTIME_DIR / "assets"
LOG_DIR = PROJECT_DIR / "logs"
ECHO_LOG_MAX_BYTES = int(os.environ.get("JARVIS_ECHO_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
ECHO_LOG_BACKUP_COUNT = int(os.environ.get("JARVIS_ECHO_LOG_BACKUP_COUNT", "3"))
if ECHO_LOG_MAX_BYTES <= 0 or ECHO_LOG_BACKUP_COUNT <= 0:
    raise ValueError("JARVIS_ECHO_LOG_MAX_BYTES and JARVIS_ECHO_LOG_BACKUP_COUNT must be positive")


# ---------- Audio ----------

# Python/sounddevice input device. Prefer a stable name/hint over a numeric
# PortAudio index because indexes can change after reboot.
AUDIO_DEVICE = _audio_device(os.environ.get("JARVIS_AUDIO_DEVICE", "default"))
ECHO_BIND = os.environ.get("JARVIS_ECHO_BIND", "127.0.0.1")
ECHO_PORT = int(os.environ.get("JARVIS_ECHO_PORT", "8766"))
ECHO_DEVICE_ID = os.environ.get("JARVIS_ECHO_DEVICE_ID", "")
ECHO_TOKEN = os.environ.get("JARVIS_ECHO_TOKEN", "")
ECHO_NATIVE_WAKE = _env_bool("JARVIS_ECHO_NATIVE_WAKE", False)
ECHO_WAKE_THRESHOLD = float(os.environ.get("JARVIS_ECHO_WAKE_THRESHOLD", "0.5"))
if not 0 < ECHO_WAKE_THRESHOLD <= 1:
    raise ValueError("JARVIS_ECHO_WAKE_THRESHOLD must be greater than 0 and at most 1")

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
SPEAKER_PROFILES_PATH = _env_path(
    "JARVIS_SPEAKER_PROFILES_PATH", PROJECT_DIR / "speaker_profiles.json"
)
SPEAKER_VOLUME_OVERRIDES = {
    key: os.environ[env]
    for key, env in {
        "card": "JARVIS_VOLUME_CARD",
        "control": "JARVIS_VOLUME_CONTROL",
        "level": "JARVIS_VOLUME_LEVEL",
    }.items()
    if env in os.environ
}

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
WHISPER_CPP_DIR = WHISPER_CPP_DIR.absolute()
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
COMMAND_SILENCE_SECONDS = float(os.environ.get("JARVIS_COMMAND_SILENCE_SECONDS", "2.0"))
if not 0 < COMMAND_SILENCE_SECONDS <= 10:
    raise ValueError("JARVIS_COMMAND_SILENCE_SECONDS must be greater than 0 and at most 10")
COMMAND_MIN_RECORD_SECONDS = 0.7
COMMAND_AUDIO_RMS_THRESHOLD = int(os.environ.get("JARVIS_COMMAND_AUDIO_RMS_THRESHOLD", "420"))
if COMMAND_AUDIO_RMS_THRESHOLD <= 0:
    raise ValueError("JARVIS_COMMAND_AUDIO_RMS_THRESHOLD must be positive")
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
            ]
        ),
    ).split(",")
    if phrase.strip()
]


# ---------- Wake word ----------

# For now, we are using Vosk based wake detection.
# Keep longer phrases before shorter words so command cleanup works well.
_default_wake_words = [
    "hello jarvis",
    "hey jarvis",
    "hi jarvis",
    "hello computer",
    "hey computer",
    "jarvis",
    "computer",
    "hello",
]
WAKE_WORDS = [
    " ".join(phrase.lower().split())
    for phrase in os.environ.get("JARVIS_WAKE_WORDS", ",".join(_default_wake_words)).split(",")
    if phrase.strip()
]
if not WAKE_WORDS:
    raise ValueError("JARVIS_WAKE_WORDS must contain at least one wake phrase")

# 0 = only wake on exact phrases in WAKE_WORDS.
# 100 = wake on any recognized speech.
# Values in between lower the similarity needed to treat speech as a wake phrase.
LENIENT_WAKE_LEVEL = max(0, min(100, int(os.environ.get("JARVIS_LENIENT_WAKE_LEVEL", "0"))))


# ---------- Local AI API ----------

API_BASE_URL = os.environ.get(
    "JARVIS_API_BASE_URL",
    "http://127.0.0.1:1235/v1/agents/jarvis",
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
CONTINUE_LISTENING_DEFAULT = _env_bool("JARVIS_CONTINUE_LISTENING_DEFAULT", False)


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

# Direct Echo: return to wake standby if speech has not begun. These do not
# shorten the overall recording windows once the user starts speaking.
HASSMIC_WAKE_WAIT_SECONDS = float(os.environ.get("JARVIS_HASSMIC_WAKE_WAIT_SECONDS", "5"))
HASSMIC_FOLLOWUP_WAIT_SECONDS = float(os.environ.get("JARVIS_HASSMIC_FOLLOWUP_WAIT_SECONDS", "5"))
for _wait_name, _wait_value in (
    ("JARVIS_HASSMIC_WAKE_WAIT_SECONDS", HASSMIC_WAKE_WAIT_SECONDS),
    ("JARVIS_HASSMIC_FOLLOWUP_WAIT_SECONDS", HASSMIC_FOLLOWUP_WAIT_SECONDS),
):
    if not 0 < _wait_value <= 60:
        raise ValueError(f"{_wait_name} must be greater than 0 and at most 60")

# Prevent duplicate wake triggers.
DUPLICATE_WAKE_SECONDS = 3

# Local voice control: how long "Jarvis stand down" disables wake listening.
STAND_DOWN_SECONDS = int(os.environ.get("JARVIS_STAND_DOWN_SECONDS", "3600"))

# If the Pi fails to capture a command after wake, return to wake mode quietly.
COMMAND_RETRY_COUNT = 1

# If the API/server call fails, retry this many times.
API_RETRY_COUNT = 2

# ---------- Local Jarvis command server ----------

COMMAND_SERVER_ENABLED = _env_bool("JARVIS_COMMAND_SERVER_ENABLED", True)
COMMAND_SERVER_PORT = int(os.environ.get("JARVIS_COMMAND_SERVER_PORT", "8765"))
COMMAND_SERVER_TOKEN = os.environ.get("JARVIS_COMMAND_SERVER_TOKEN", "").strip()
COMMAND_SERVER_HOST = os.environ.get(
    "JARVIS_COMMAND_SERVER_HOST",
    "0.0.0.0" if COMMAND_SERVER_TOKEN else "127.0.0.1",
)
COMMAND_SERVER_MAX_BODY_BYTES = int(os.environ.get("JARVIS_COMMAND_SERVER_MAX_BODY_BYTES", "65536"))
COMMAND_SERVER_READ_TIMEOUT = float(os.environ.get("JARVIS_COMMAND_SERVER_READ_TIMEOUT", "10"))
COMMAND_SERVER_MAX_CONNECTIONS = int(os.environ.get("JARVIS_COMMAND_SERVER_MAX_CONNECTIONS", "16"))
if not 1 <= COMMAND_SERVER_MAX_BODY_BYTES <= 1048576:
    raise ValueError("JARVIS_COMMAND_SERVER_MAX_BODY_BYTES must be between 1 and 1048576")
if not 0 < COMMAND_SERVER_READ_TIMEOUT <= 60:
    raise ValueError("JARVIS_COMMAND_SERVER_READ_TIMEOUT must be greater than 0 and at most 60")
if not 1 <= COMMAND_SERVER_MAX_CONNECTIONS <= 128:
    raise ValueError("JARVIS_COMMAND_SERVER_MAX_CONNECTIONS must be between 1 and 128")


# ---------- Voice / TTS ----------

# Piper American female voice.
# None preserves the voice model's own timing default.
_piper_length_scale = os.environ.get("JARVIS_PIPER_LENGTH_SCALE", "").strip()
PIPER_LENGTH_SCALE = float(_piper_length_scale) if _piper_length_scale else None
if PIPER_LENGTH_SCALE is not None and not 0.5 <= PIPER_LENGTH_SCALE <= 3.0:
    raise ValueError("JARVIS_PIPER_LENGTH_SCALE must be between 0.5 and 3.0")
# Extra silence between Piper's sentence chunks, not after the final sentence.
PIPER_SENTENCE_SILENCE = float(os.environ.get("JARVIS_PIPER_SENTENCE_SILENCE", "0.25"))
if not 0 <= PIPER_SENTENCE_SILENCE <= 2.0:
    raise ValueError("JARVIS_PIPER_SENTENCE_SILENCE must be between 0 and 2.0")
PIPER_BINARY = os.environ.get("JARVIS_PIPER_BINARY", "piper")
PIPER_BACKEND = os.environ.get("JARVIS_PIPER_BACKEND", "cli").strip().lower()
if PIPER_BACKEND not in {"cli", "python"}:
    raise ValueError("JARVIS_PIPER_BACKEND must be cli or python")
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
CHECKING_REPLY_DELAY_SECONDS = 4.0
WAITING_ANNOUNCEMENTS = _env_bool("JARVIS_WAITING_ANNOUNCEMENTS", True)
STILL_CHECKING_REPLIES = [
    "Still checking.",
    "Almost there.",
    "Still looking.",
    "One more moment.",
    "Working on it.",
]
STILL_CHECKING_REPLY_DELAY_SECONDS = 9.0
UNCLEAR_FOLLOWUP_REPLIES = [
    "I heard something, but I didn't catch the words.",
    "Sorry, I didn't catch that.",
    "I missed that. Could you say it again?",
]
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

# Experimental direct echo-dot-assist controller (opt-in entry point).
ECHO_DEVICES_PATH = (_env_path("JARVIS_ECHO_DEVICES_PATH", PROJECT_DIR / "echo_devices.json")
                     if os.environ.get("JARVIS_ECHO_DEVICES_PATH", "").strip() else "")
HASSMIC_HOST = os.environ.get("JARVIS_HASSMIC_HOST", "").strip()
STREAMING_ENABLED = _env_bool("JARVIS_STREAMING_ENABLED", False)
STREAMING_INPUT_ENABLED = _env_bool("JARVIS_STREAMING_INPUT_ENABLED", False)
STREAMING_WHISPER_THREADS = int(os.environ.get("JARVIS_STREAMING_WHISPER_THREADS", str(WHISPER_THREADS)))
if not 1 <= STREAMING_WHISPER_THREADS <= 32:
    raise ValueError("JARVIS_STREAMING_WHISPER_THREADS must be between 1 and 32")
STREAMING_STT_INTERVAL = float(os.environ.get("JARVIS_STREAMING_STT_INTERVAL", "1.0"))
if not 0.2 <= STREAMING_STT_INTERVAL <= 10:
    raise ValueError("JARVIS_STREAMING_STT_INTERVAL must be between 0.2 and 10")
VOICE_PROFILE_DIR = _env_path("JARVIS_VOICE_PROFILE_DIR", Path(LOG_DIR) / "voice_profiles")
HASSMIC_PORT = int(os.environ.get("JARVIS_HASSMIC_PORT", "16700"))
if not 1 <= HASSMIC_PORT <= 65535:
    raise ValueError("JARVIS_HASSMIC_PORT must be between 1 and 65535")
