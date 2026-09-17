import math
import os
import queue
import subprocess
import sys
import wave
from array import array

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


ONLINE_TONE_PATH = "/tmp/jarvis-online.wav"
COMMAND_CAPTURED_TONE_PATH = "/tmp/jarvis-command-captured.wav"
TONE_SAMPLE_RATE = 16000
PLAYBACK_FALLBACK_DEVICES = ["default"]


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


def write_tone(path: str, notes: list[tuple[float, float]], volume: float = 0.35):
    samples = array("h")
    amplitude = int(32767 * volume)

    for frequency, duration in notes:
        frame_count = int(TONE_SAMPLE_RATE * duration)
        for frame in range(frame_count):
            if frequency <= 0:
                samples.append(0)
                continue

            envelope = min(1.0, frame / 400, (frame_count - frame) / 400)
            value = math.sin(2 * math.pi * frequency * frame / TONE_SAMPLE_RATE)
            samples.append(int(amplitude * envelope * value))

    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(TONE_SAMPLE_RATE)
        wav.writeframes(samples.tobytes())


def play_online_tone():
    os.makedirs(os.path.dirname(ONLINE_TONE_PATH), exist_ok=True)
    write_tone(
        ONLINE_TONE_PATH,
        [
            (784.0, 0.11),
            (0.0, 0.04),
            (1046.5, 0.15),
        ],
    )
    play_wav_file(ONLINE_TONE_PATH)


def play_command_captured_tone():
    os.makedirs(os.path.dirname(COMMAND_CAPTURED_TONE_PATH), exist_ok=True)
    write_tone(
        COMMAND_CAPTURED_TONE_PATH,
        [
            (1318.5, 0.055),
            (0.0, 0.025),
            (1760.0, 0.075),
        ],
        volume=0.22,
    )
    play_wav_file(COMMAND_CAPTURED_TONE_PATH)


def alsa_devices():
    devices = [str(PLAYBACK_DEVICE)]
    for device in PLAYBACK_FALLBACK_DEVICES:
        device = str(device)
        if device not in devices:
            devices.append(device)
    return devices


def play_wav_with_alsa(path: str, model=None):
    ensure_speaker_volume()
    devices = alsa_devices()

    for index, device in enumerate(devices):
        aplay = subprocess.Popen(
            [
                "aplay",
                "-D",
                device,
                path,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        if model is None:
            _, stderr = aplay.communicate()
            if aplay.returncode == 0:
                return

            print(f"aplay error on {device}:", stderr.strip())
            if index < len(devices) - 1:
                continue

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

        _, stderr = aplay.communicate()
        if aplay.returncode == 0:
            return

        print(f"aplay error on {device}:", stderr.strip())


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
