import json
import time

from vosk import KaldiRecognizer

from config import (
    DUPLICATE_WAKE_SECONDS,
    LENIENT_WAKE_PARTIALS,
    SAMPLE_RATE,
    WAKE_WORDS,
)


def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def has_wake_word(text: str) -> bool:
    heard = normalize_text(text)
    wake_phrases = [*WAKE_WORDS, *LENIENT_WAKE_PARTIALS]
    return any(wake in heard for wake in wake_phrases)


class WakeWordMonitor:
    def __init__(self, model):
        self.model = model
        self.recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        self.last_trigger_time = 0

    def reset(self):
        self.recognizer = KaldiRecognizer(self.model, SAMPLE_RATE)

    def accept_audio(self, data: bytes) -> bool:
        if not self.recognizer.AcceptWaveform(data):
            partial = json.loads(self.recognizer.PartialResult()).get("partial", "")
            return has_wake_word(partial)

        result = json.loads(self.recognizer.Result())
        heard = result.get("text", "").lower().strip()

        if heard:
            print("Heard:", heard)

        if not has_wake_word(heard):
            return False

        now = time.time()
        if now - self.last_trigger_time < DUPLICATE_WAKE_SECONDS:
            return False

        self.last_trigger_time = now
        return True
