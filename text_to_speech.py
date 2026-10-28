import os
import re
import shutil
import subprocess
import sys
import threading
import wave
from pathlib import Path

from config import (
    EMPTY_RESPONSE_REPLY,
    MAX_TTS_CHARS,
    PIPER_BINARY,
    PIPER_BACKEND,
    PIPER_LENGTH_SCALE,
    PIPER_SENTENCE_SILENCE,
    PIPER_MODEL_PATH,
    REPLY_WAV_PATH,
)

_voice_lock = threading.Lock()
_cached_voice = None
_cached_model_path = None


def synthesize_with_cached_voice(text: str, output_path: str):
    """Reuse one voice; serialize its phonemizer and output generation."""
    global _cached_voice, _cached_model_path
    from piper import PiperVoice

    model_path = str(Path(PIPER_MODEL_PATH).resolve())
    with _voice_lock:
        if _cached_voice is None or _cached_model_path != model_path:
            voice = PiperVoice.load(model_path)
            _cached_voice, _cached_model_path = voice, model_path
        with wave.open(str(output_path), "wb") as output:
            options = {}
            if PIPER_LENGTH_SCALE is not None:
                from piper import SynthesisConfig
                options['syn_config'] = SynthesisConfig(length_scale=PIPER_LENGTH_SCALE)
            if PIPER_SENTENCE_SILENCE == 0:
                _cached_voice.synthesize_wav(text, output, **options)
                return
            audio_format = None
            for chunk in _cached_voice.synthesize(text, **options):
                chunk_format = (chunk.sample_channels, chunk.sample_width, chunk.sample_rate)
                if audio_format is None:
                    audio_format = chunk_format
                    output.setparams((*audio_format, 0, 'NONE', 'not compressed'))
                else:
                    if chunk_format != audio_format:
                        raise ValueError('Piper changed audio format between sentences')
                    # Round to complete frames before converting to bytes.
                    frames = int(chunk.sample_rate * PIPER_SENTENCE_SILENCE)
                    output.writeframes(bytes(frames * chunk.sample_width * chunk.sample_channels))
                output.writeframes(chunk.audio_int16_bytes)
            if audio_format is None:
                # Punctuation-only input can produce no chunks; still write a valid WAV.
                output.setparams((1, 2, _cached_voice.config.sample_rate, 0, 'NONE', 'not compressed'))


def clean_for_tts(text: str) -> str:
    text = text.strip()

    text = re.sub(r"^\[Jarvis\]\s*", "", text)
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"°\s*[fFcC]\b", " degrees ", text)
    text = text.replace("°", " degrees ")
    text = text.replace("%", " percent ")
    text = text.replace("&", " and ")
    text = text.replace("@", " at ")
    text = text.replace("+", " plus ")
    text = text.replace("’", "'").replace("‘", "'")
    text = re.sub(r"(?<=\d)[–—](?=\d)", " to ", text)
    # Convert typographic clause breaks to a familiar prosody cue; preserve hyphens.
    text = re.sub(r"\s*[–—]\s*", ", ", text)
    text = re.sub(r"[/\\|~^*_`#<>{}\[\]()=]+", " ", text)
    text = re.sub(r"[\"“”]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = text.strip()

    return text[:MAX_TTS_CHARS].strip()


def resolve_piper_binary() -> str:
    """Find Piper on PATH or beside the active virtual environment's Python."""
    executable = shutil.which(PIPER_BINARY)
    if executable:
        return executable

    if Path(PIPER_BINARY).name == PIPER_BINARY:
        executable_names = [PIPER_BINARY]
        if not PIPER_BINARY.lower().endswith(".exe"):
            executable_names.append(f"{PIPER_BINARY}.exe")

        for executable_name in executable_names:
            venv_executable = Path(sys.executable).with_name(executable_name)
            if venv_executable.is_file():
                return str(venv_executable)

    return PIPER_BINARY


def synthesize_to_wav(text: str, output_path: str = REPLY_WAV_PATH) -> str:
    text = clean_for_tts(text)

    if not text:
        text = EMPTY_RESPONSE_REPLY

    print("Jarvis:", text)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if PIPER_BACKEND == "python":
        synthesize_with_cached_voice(text, output_path)
        return output_path

    env = dict(os.environ)
    env["ORT_LOG_SEVERITY_LEVEL"] = "3"

    subprocess.run(
        [
            resolve_piper_binary(),
            "--model",
            PIPER_MODEL_PATH,
            "--output_file",
            output_path,
            *(["--sentence-silence", str(PIPER_SENTENCE_SILENCE)]
              if PIPER_SENTENCE_SILENCE else []),
            *(["--length_scale", str(PIPER_LENGTH_SCALE)]
              if PIPER_LENGTH_SCALE is not None else []),
        ],
        input=text,
        text=True,
        encoding="utf-8",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    return output_path
