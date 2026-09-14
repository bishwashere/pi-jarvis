import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config import (
    EMPTY_RESPONSE_REPLY,
    MAX_TTS_CHARS,
    PIPER_BINARY,
    PIPER_MODEL_PATH,
    REPLY_WAV_PATH,
)


def clean_for_tts(text: str) -> str:
    text = text.strip()

    text = re.sub(r"^\[Pasture\]\s*", "", text)
    text = re.sub(r"[*_`#>\[\]]", "", text)
    text = re.sub(r"\s+", " ", text)

    return text[:MAX_TTS_CHARS]


def resolve_piper_binary() -> str:
    """Find Piper on PATH or beside the active virtual environment's Python."""
    executable = shutil.which(PIPER_BINARY)
    if executable:
        return executable

    if Path(PIPER_BINARY).name == PIPER_BINARY:
        venv_executable = Path(sys.executable).with_name(PIPER_BINARY)
        if venv_executable.is_file():
            return str(venv_executable)

    return PIPER_BINARY


def synthesize_to_wav(text: str, output_path: str = REPLY_WAV_PATH) -> str:
    text = clean_for_tts(text)

    if not text:
        text = EMPTY_RESPONSE_REPLY

    print("Jarvis:", text)

    env = dict(os.environ)
    env["ORT_LOG_SEVERITY_LEVEL"] = "3"
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    subprocess.run(
        [
            resolve_piper_binary(),
            "--model",
            PIPER_MODEL_PATH,
            "--output_file",
            output_path,
        ],
        input=text,
        text=True,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    return output_path
