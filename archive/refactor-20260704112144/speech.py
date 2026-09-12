import os
import queue
import re
import subprocess

from config import (
    EMPTY_RESPONSE_REPLY,
    MAX_TTS_CHARS,
    PIPER_MODEL_PATH,
    PLAYBACK_DEVICE,
)

PIPER_SAMPLE_RATE = "22050"


def clean_for_tts(text: str) -> str:
    text = text.strip()

    # Remove Pasture prefix if present.
    text = re.sub(r"^\[Pasture\]\s*", "", text)

    # Remove common markdown characters that sound bad in TTS.
    text = re.sub(r"[*_`#>\[\]]", "", text)

    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text)

    return text[:MAX_TTS_CHARS]


def stop_process(process):
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def speak(text: str, model=None):
    text = clean_for_tts(text)

    if not text:
        text = EMPTY_RESPONSE_REPLY

    print("Jarvis:", text)

    env = dict(os.environ)

    # Hide harmless ONNX Runtime GPU/device warnings from Piper.
    env["ORT_LOG_SEVERITY_LEVEL"] = "3"

    piper = subprocess.Popen(
        [
            "piper",
            "--model",
            PIPER_MODEL_PATH,
            "--output-raw",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )

    aplay = subprocess.Popen(
        [
            "aplay",
            "-D",
            PLAYBACK_DEVICE,
            "-r",
            PIPER_SAMPLE_RATE,
            "-f",
            "S16_LE",
            "-t",
            "raw",
            "-",
        ],
        stdin=piper.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if piper.stdin:
        piper.stdin.write(text)
        piper.stdin.close()

    if piper.stdout:
        piper.stdout.close()

    if model is None:
        piper.wait()
        aplay.wait()
        return

    from audio_runtime import audio_queue
    from wake import WakeWordInterrupted, WakeWordMonitor

    monitor = WakeWordMonitor(model)

    try:
        while aplay.poll() is None:
            try:
                data = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if monitor.accept_audio(data):
                stop_process(aplay)
                stop_process(piper)
                raise WakeWordInterrupted()
    finally:
        stop_process(aplay)
        stop_process(piper)
