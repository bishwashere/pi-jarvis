import queue
import subprocess
import sys
import wave

import sounddevice as sd

from config import (
    CONFIGURE_VOLUME,
    PLAYBACK_BACKEND,
    PLAYBACK_DEVICE,
    VOLUME_CARD,
    VOLUME_CONTROL,
    VOLUME_LEVEL,
)
from detect_wake_word import WakeWordMonitor
from interruptions import WakeWordInterrupted
from listen_to_mic import audio_queue


def stop_process(process):
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def ensure_speaker_volume():
    if not CONFIGURE_VOLUME:
        return

    subprocess.run(
        ["amixer", "-c", VOLUME_CARD, "sset", VOLUME_CONTROL, VOLUME_LEVEL],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def resolve_playback_backend() -> str:
    backend = PLAYBACK_BACKEND.strip().lower()
    if backend == "auto":
        return "alsa" if sys.platform.startswith("linux") else "sounddevice"
    if backend not in {"alsa", "sounddevice"}:
        raise ValueError(
            "JARVIS_PLAYBACK_BACKEND must be 'auto', 'alsa', or 'sounddevice'"
        )
    return backend


def sounddevice_output_device(device):
    if device is None:
        return None
    if isinstance(device, str) and device.strip().lower() in {"", "default"}:
        return None
    return device


def play_wav_with_alsa(path: str, model=None):
    ensure_speaker_volume()

    aplay = subprocess.Popen(
        [
            "aplay",
            "-D",
            str(PLAYBACK_DEVICE),
            path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    if model is None:
        _, stderr = aplay.communicate()
        if aplay.returncode != 0:
            print("aplay error:", stderr.strip())
        return

    monitor = WakeWordMonitor(model)

    try:
        while aplay.poll() is None:
            try:
                data = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if monitor.accept_audio(data):
                stop_process(aplay)
                raise WakeWordInterrupted()
    finally:
        stop_process(aplay)


def play_wav_with_sounddevice(path: str, model=None):
    sample_formats = {
        1: "uint8",
        2: "int16",
        3: "int24",
        4: "int32",
    }
    output_device = sounddevice_output_device(PLAYBACK_DEVICE)
    monitor = WakeWordMonitor(model) if model is not None else None

    with wave.open(path, "rb") as audio:
        if audio.getcomptype() != "NONE":
            raise ValueError("sounddevice playback requires an uncompressed WAV file")

        sample_width = audio.getsampwidth()
        if sample_width not in sample_formats:
            raise ValueError(f"unsupported WAV sample width: {sample_width} bytes")

        with sd.RawOutputStream(
            samplerate=audio.getframerate(),
            channels=audio.getnchannels(),
            dtype=sample_formats[sample_width],
            device=output_device,
        ) as stream:
            while data := audio.readframes(4096):
                if stream.write(data):
                    print("Audio output underflow.", flush=True)

                if monitor is None:
                    continue

                while True:
                    try:
                        microphone_data = audio_queue.get_nowait()
                    except queue.Empty:
                        break

                    if monitor.accept_audio(microphone_data):
                        raise WakeWordInterrupted()


def play_wav_file(path: str, model=None):
    backend = resolve_playback_backend()
    if backend == "alsa":
        return play_wav_with_alsa(path, model=model)
    return play_wav_with_sounddevice(path, model=model)
