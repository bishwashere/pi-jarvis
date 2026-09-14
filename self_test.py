"""Hardware-safe smoke test for a Pi Jarvis checkout.

This deliberately avoids the microphone, speaker, Jarvis API, and optional
whisper.cpp installation.  It validates the bundled models and the local
Python/Piper runtime so developers can distinguish setup problems from missing
external services or Raspberry Pi hardware.
"""

import shutil
import tempfile
import wave
from pathlib import Path

from vosk import Model, SetLogLevel

from call_agent_api import parse_agent_reply
from config import (
    COMMAND_STT_ENGINE,
    PIPER_MODEL_PATH,
    PROJECT_DIR,
    VOSK_MODEL_PATH,
    WHISPER_CPP_BINARY,
    WHISPER_MODEL_PATH,
)
from detect_wake_word import get_wake_match
from text_to_speech import resolve_piper_binary, synthesize_to_wav


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")


def require_directory(path: Path, label: str) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"{label} not found: {path}")


def check_configuration() -> str:
    vosk_path = Path(VOSK_MODEL_PATH)
    piper_path = Path(PIPER_MODEL_PATH)
    require_directory(vosk_path, "Vosk model directory")
    require_file(vosk_path / "am/final.mdl", "Vosk acoustic model")
    require_file(piper_path, "Piper voice model")
    require_file(Path(f"{piper_path}.json"), "Piper voice configuration")
    return f"assets resolve from {PROJECT_DIR}"


def check_core_logic() -> str:
    reply = parse_agent_reply('{"reply":"Ready","continue_listening":true}')
    if reply != {"reply": "Ready", "continue_listening": True}:
        raise AssertionError(f"unexpected API response parsing result: {reply}")
    if not get_wake_match("hey jarvis").get("triggered"):
        raise AssertionError("configured wake phrase was not recognized")
    return "wake matching and API response parsing"


def check_vosk_model() -> str:
    SetLogLevel(-1)
    Model(VOSK_MODEL_PATH)
    return "bundled wake-word model loads"


def check_piper() -> str:
    piper_binary = resolve_piper_binary()
    if not Path(piper_binary).is_file() and not shutil.which(piper_binary):
        raise FileNotFoundError(f"Piper executable not found: {piper_binary}")

    with tempfile.TemporaryDirectory(prefix="pi-jarvis-self-test-") as temp_dir:
        output_path = Path(temp_dir) / "reply.wav"
        synthesize_to_wav("Pi Jarvis local self test.", str(output_path))

        with wave.open(str(output_path), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getnframes() == 0:
                raise AssertionError("Piper generated an invalid WAV file")
            sample_rate = audio.getframerate()

    return f"speech synthesis produces mono {sample_rate} Hz WAV audio"


def describe_optional_runtime() -> None:
    whisper_binary = Path(WHISPER_CPP_BINARY)
    whisper_model = Path(WHISPER_MODEL_PATH)
    whisper_ready = whisper_binary.is_file() and whisper_model.is_file()
    status = "ready" if whisper_ready else "not installed"
    print(f"[info] command STT engine: {COMMAND_STT_ENGINE}")
    print(f"[info] optional whisper.cpp runtime: {status}")
    if not whisper_ready:
        print("[info] run_local.sh selects bundled Vosk for command transcription")


def main() -> int:
    checks = [
        ("configuration", check_configuration),
        ("core logic", check_core_logic),
        ("Vosk", check_vosk_model),
        ("Piper", check_piper),
    ]
    failures = []

    for label, check in checks:
        try:
            detail = check()
        except Exception as error:
            failures.append((label, error))
            print(f"[fail] {label}: {error}")
        else:
            print(f"[ok] {label}: {detail}")

    describe_optional_runtime()

    if failures:
        print(f"Local self-test failed ({len(failures)} check(s)).")
        return 1

    print("Local self-test passed. No microphone, speaker, or API was used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
