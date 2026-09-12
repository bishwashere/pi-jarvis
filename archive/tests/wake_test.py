import json
import queue
import subprocess
import time

import sounddevice as sd
from vosk import Model, KaldiRecognizer

DEVICE = 2
SAMPLE_RATE = 16000
MODEL_PATH = "vosk-model-small-en-us-0.15"
WAKE_WORDS = ["hello", "jarvis", "hey jarvis"]

q = queue.Queue()

def speak(text):
    subprocess.run(
        ["espeak-ng", "-w", "reply.wav", text],
        check=True
    )
    subprocess.run(
        ["aplay", "-D", "plughw:2,0", "reply.wav"],
        check=True
    )

def callback(indata, frames, time_info, status):
    if status:
        print(status)
    q.put(bytes(indata))

model = Model(MODEL_PATH)
recognizer = KaldiRecognizer(model, SAMPLE_RATE)

print("Jarvis wake test running.")
print("Say: Jarvis")
print("Press Ctrl+C to stop.")

last_trigger = 0

try:
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=4000,
        device=DEVICE,
        dtype="int16",
        channels=1,
        callback=callback,
    ):
        while True:
            data = q.get()

            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").lower().strip()

                if text:
                    print("Heard:", text)

                if any(wake in text for wake in WAKE_WORDS):
                    now = time.time()

                    # Avoid repeated triggers from the same phrase/noise
                    if now - last_trigger > 2:
                        last_trigger = now
                        print("Wake word detected.")
                        speak("Hello, I am listening.")

except KeyboardInterrupt:
    print("\nStopped.")
