import queue
import subprocess

from config import (
    CONFIGURE_VOLUME,
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


def play_wav_file(path: str, model=None):
    ensure_speaker_volume()

    aplay = subprocess.Popen(
        [
            "aplay",
            "-D",
            PLAYBACK_DEVICE,
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
