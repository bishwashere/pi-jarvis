import json
import queue
import sounddevice as sd
from vosk import Model, KaldiRecognizer

DEVICE = 2
SAMPLE_RATE = 16000
MODEL_PATH = "vosk-model-small-en-us-0.15"

q = queue.Queue()

def callback(indata, frames, time, status):
    if status:
        print(status)
    q.put(bytes(indata))

model = Model(MODEL_PATH)
recognizer = KaldiRecognizer(model, SAMPLE_RATE)

print("Speak clearly. Try: hello jarvis what time is it")
print("Press Ctrl+C to stop.")

last_partial = ""

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
                text = result.get("text", "")
                if text:
                    print("\nFINAL:", text)
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "")
                if partial and partial != last_partial:
                    print("partial:", partial)
                    last_partial = partial

except KeyboardInterrupt:
    final = json.loads(recognizer.FinalResult()).get("text", "")
    if final:
        print("\nFINAL:", final)
    print("\nStopped.")
