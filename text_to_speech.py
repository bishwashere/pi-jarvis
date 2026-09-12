import os
import re
import subprocess

from config import EMPTY_RESPONSE_REPLY, MAX_TTS_CHARS, PIPER_MODEL_PATH, REPLY_WAV_PATH


def clean_for_tts(text: str) -> str:
    text = text.strip()

    text = re.sub(r"^\[Pasture\]\s*", "", text)
    text = re.sub(r"[*_`#>\[\]]", "", text)
    text = re.sub(r"\s+", " ", text)

    return text[:MAX_TTS_CHARS]


def synthesize_to_wav(text: str, output_path: str = REPLY_WAV_PATH) -> str:
    text = clean_for_tts(text)

    if not text:
        text = EMPTY_RESPONSE_REPLY

    print("Jarvis:", text)

    env = dict(os.environ)
    env["ORT_LOG_SEVERITY_LEVEL"] = "3"

    subprocess.run(
        [
            "piper",
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
