# ---------- Audio ----------

# Python/sounddevice input device. Prefer a stable name/hint over a numeric
# PortAudio index because indexes can change after reboot.
AUDIO_DEVICE = "default"
AUDIO_DEVICE_FALLBACKS = [
    "pulse",
    "P10S: USB Audio",
    "USB Audio",
    0,
]

# ALSA playback device for your USB speaker.
PLAYBACK_DEVICE = "plughw:2,0"

SAMPLE_RATE = 16000
VOSK_MODEL_PATH = "/home/jarvis/jarvis/runtime/assets/vosk-model-small-en-us-0.15"


# ---------- Speech to text ----------

# Vosk is still used for wake detection. This controls command transcription.
# Use "vosk" to go back to the original streaming recognizer.
COMMAND_STT_ENGINE = "whisper"

# Local whisper.cpp test setup.
WHISPER_CPP_BINARY = "/home/jarvis/whisper.cpp/build/bin/whisper-cli"
WHISPER_MODEL_PATH = "/home/jarvis/whisper.cpp/models/ggml-tiny.en.bin"
WHISPER_THREADS = 1
COMMAND_RECORDING_PATH = "/home/jarvis/jarvis/logs/command.wav"
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

API_URL = "http://192.168.1.82:1235/v1/agents/jarvis/chat/completions"
API_HEALTH_URL = "http://192.168.1.82:1235/v1/agents/jarvis/health"
API_MODEL = "api-assistant"

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
PIPER_MODEL_PATH = "/home/jarvis/jarvis/runtime/assets/piper/en_US-amy-medium.onnx"

# Used only if you use file based playback.
REPLY_WAV_PATH = "/home/jarvis/jarvis/logs/reply.wav"

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
