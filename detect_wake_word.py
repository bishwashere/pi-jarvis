import json
import time
from difflib import SequenceMatcher

from vosk import KaldiRecognizer

from config import (
    DUPLICATE_WAKE_SECONDS,
    LENIENT_WAKE_LEVEL,
    SAMPLE_RATE,
    WAKE_WORDS,
)

def normalize_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def iter_candidate_phrases(heard: str):
    yield heard

    words = heard.split()
    wake_lengths = {len(wake.split()) for wake in WAKE_WORDS}

    for phrase_length in wake_lengths:
        if phrase_length >= len(words):
            continue

        for start in range(len(words) - phrase_length + 1):
            yield " ".join(words[start : start + phrase_length])


def wake_similarity(candidate: str, wake: str) -> float:
    if not candidate or candidate[0] != wake[0]:
        return 0.0

    if len(candidate) < 3 or len(candidate) < len(wake) * 0.6:
        return 0.0

    return SequenceMatcher(None, candidate, wake).ratio()


def get_wake_match(text: str, allow_lenient: bool = True) -> dict:
    heard = normalize_text(text)
    if not heard:
        return {"triggered": False}

    for wake in WAKE_WORDS:
        if wake in heard:
            return {
                "triggered": True,
                "mode": "strict",
                "heard": heard,
                "matched": wake,
                "candidate": wake,
                "score": 1.0,
            }

    if not allow_lenient:
        return {"triggered": False, "heard": heard, "mode": "strict-only"}

    level = max(0, min(100, LENIENT_WAKE_LEVEL))
    if level <= 0:
        return {"triggered": False, "heard": heard, "level": level}

    if level >= 100:
        return {
            "triggered": True,
            "mode": "lenient-any",
            "heard": heard,
            "matched": "*",
            "candidate": heard,
            "score": 1.0,
            "level": level,
        }

    threshold = 1.0 - (level / 100)
    best = {"score": 0.0, "candidate": "", "matched": ""}

    for candidate in iter_candidate_phrases(heard):
        for wake in WAKE_WORDS:
            score = wake_similarity(candidate, wake)
            if score > best["score"]:
                best = {"score": score, "candidate": candidate, "matched": wake}

    if best["score"] >= threshold:
        return {
            "triggered": True,
            "mode": "lenient",
            "heard": heard,
            "matched": best["matched"],
            "candidate": best["candidate"],
            "score": best["score"],
            "threshold": threshold,
            "level": level,
        }

    return {
        "triggered": False,
        "heard": heard,
        "best": best,
        "threshold": threshold,
        "level": level,
    }


def has_strict_wake_word(text: str) -> bool:
    heard = normalize_text(text)
    return any(wake in heard for wake in WAKE_WORDS)


def has_wake_word(text: str) -> bool:
    return get_wake_match(text)["triggered"]


class WakeWordMonitor:
    def __init__(self, model):
        self.model = model
        self.recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        self.last_trigger_time = 0
        self.last_partial = ""

    def reset(self):
        self.recognizer = KaldiRecognizer(self.model, SAMPLE_RATE)
        self.last_partial = ""

    def log_wake_match(self, match: dict, source: str):
        if match.get("mode") == "strict":
            print(
                "Wake match: "
                f"source={source} "
                f"heard='{match['heard']}' "
                f"matched='{match['matched']}'",
                flush=True,
            )
            return

        print(
            "Lenient wake match: "
            f"source={source} "
            f"heard='{match['heard']}' "
            f"candidate='{match['candidate']}' "
            f"matched='{match['matched']}' "
            f"score={match['score']:.2f} "
            f"level={match.get('level')}",
            flush=True,
        )

    def accept_audio(self, data: bytes) -> bool:
        if not self.recognizer.AcceptWaveform(data):
            partial = json.loads(self.recognizer.PartialResult()).get("partial", "")
            if partial and partial != self.last_partial:
                print(f"Heard partial: {partial}", flush=True)
                self.last_partial = partial

            match = get_wake_match(partial, allow_lenient=False)
            if match["triggered"]:
                self.log_wake_match(match, source="partial")
            return match["triggered"]

        result = json.loads(self.recognizer.Result())
        heard = result.get("text", "").lower().strip()

        if heard:
            print("Heard:", heard)

        match = get_wake_match(heard)
        if not match["triggered"]:
            return False

        self.log_wake_match(match, source="final")

        now = time.time()
        if now - self.last_trigger_time < DUPLICATE_WAKE_SECONDS:
            return False

        self.last_trigger_time = now
        return True
