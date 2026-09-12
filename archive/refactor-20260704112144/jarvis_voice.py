import json

import sys

sys.pycache_prefix = "/home/jarvis/jarvis/runtime/cache/pycache"

from vosk import Model

from audio_runtime import audio_queue, clear_audio_queue, open_microphone_stream
from config import VOSK_MODEL_PATH, WAKE_WORDS
from conversation import handle_conversation
from wake import WakeWordMonitor


def main():
    print("Loading Vosk model...")
    model = Model(VOSK_MODEL_PATH)
    wake_monitor = WakeWordMonitor(model)

    print("Jarvis voice loop running.")
    print(f'Say one of these to wake: {", ".join(WAKE_WORDS)}')
    print("Press Ctrl+C to stop.")

    with open_microphone_stream():
        while True:
            data = audio_queue.get()

            if wake_monitor.accept_audio(data):
                handle_conversation(model)
                clear_audio_queue()
                wake_monitor.reset()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
