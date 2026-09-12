import queue

import sounddevice as sd

from config import AUDIO_DEVICE, SAMPLE_RATE


audio_queue = queue.Queue()


def audio_callback(indata, frames, time_info, status):
    if status:
        print("Audio status:", status)

    audio_queue.put(bytes(indata))


def clear_audio_queue():
    while not audio_queue.empty():
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break


def open_microphone_stream():
    return sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=4000,
        device=AUDIO_DEVICE,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    )
