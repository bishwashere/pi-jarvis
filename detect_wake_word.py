import json
import time
from difflib import SequenceMatcher

from config import (
    DUPLICATE_WAKE_SECONDS,
    LENIENT_WAKE_LEVEL,
    SAMPLE_RATE,
    WAKE_WORDS,
)
from voice_log import voice_event
from echo_audio import consume_echo_wake, set_echo_conversation_active


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


def contains_phrase(heard: str, phrase: str) -> bool:
    heard_words = heard.split()
    phrase_words = phrase.split()
    if not phrase_words or len(phrase_words) > len(heard_words):
        return False

    for start in range(len(heard_words) - len(phrase_words) + 1):
        if heard_words[start : start + len(phrase_words)] == phrase_words:
            return True

    return False


def remove_phrase(heard: str, phrase: str) -> str:
    heard_words = heard.split()
    phrase_words = phrase.split()
    if not phrase_words or len(phrase_words) > len(heard_words):
        return heard

    for start in range(len(heard_words) - len(phrase_words) + 1):
        if heard_words[start : start + len(phrase_words)] == phrase_words:
            remaining = (
                heard_words[:start]
                + heard_words[start + len(phrase_words) :]
            )
            return " ".join(remaining)

    return heard


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
        if contains_phrase(heard, wake):
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
    return any(contains_phrase(heard, wake) for wake in WAKE_WORDS)


def has_wake_word(text: str) -> bool:
    return get_wake_match(text)["triggered"]


class WakeWordMonitor:
    def __init__(self, model):
        from vosk import KaldiRecognizer

        self.model = model
        self.recognizer = KaldiRecognizer(model, SAMPLE_RATE)
        self.last_trigger_time = float("-inf")
        self.last_partial = ""
        self.last_command_after_wake = ""

    def reset(self):
        from vosk import KaldiRecognizer

        self.recognizer = KaldiRecognizer(self.model, SAMPLE_RATE)
        self.last_partial = ""
        self.last_command_after_wake = ""

    def log_wake_match(self, match: dict, source: str):
        voice_event(
            "wake_heard",
            detector="openwakeword" if source == "echo-openwakeword" else "vosk",
            source=source,
            mode=match.get("mode"),
            heard=match.get("heard"),
            matched=match.get("matched"),
            score=match.get("score"),
        )
        if match.get("mode") == "acoustic":
            print(f"Acoustic wake match: model=hey_jarvis score={match['score']:.3f}", flush=True)
            return
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

    def _accept_match(self, match, source):
        now = time.monotonic()
        if now - self.last_trigger_time < DUPLICATE_WAKE_SECONDS:
            voice_event(
                "wake_detection_ignored",
                detector="openwakeword" if source == "echo-openwakeword" else "vosk",
                source=source, reason="duplicate", matched=match.get("matched"),
                score=match.get("score"),
            )
            return False
        self.last_trigger_time = now
        self.log_wake_match(match, source=source)
        set_echo_conversation_active(True)
        return True

    def accept_audio(self, data: bytes) -> bool:
        score = consume_echo_wake()
        if score is not None:
            self.last_command_after_wake = ""
            return self._accept_match({
                "triggered": True, "mode": "acoustic",
                "matched": "hey jarvis", "score": score,
            }, "echo-openwakeword")
        if not self.recognizer.AcceptWaveform(data):
            partial = json.loads(self.recognizer.PartialResult()).get("partial", "")
            if partial and partial != self.last_partial:
                print(f"[Vosk] Heard partial: {partial}", flush=True)
                self.last_partial = partial

            match = get_wake_match(partial, allow_lenient=False)
            if match["triggered"]:
                self.last_command_after_wake = ""
                return self._accept_match(match, "partial")
            return False

        result = json.loads(self.recognizer.Result())
        heard = result.get("text", "").lower().strip()

        if heard:
            print("[Vosk] Heard:", heard, flush=True)

        match = get_wake_match(heard)
        if not match["triggered"]:
            return False

        self.last_command_after_wake = ""
        if match.get("mode") == "strict":
            command_after_wake = remove_phrase(heard, match["matched"])
            if command_after_wake:
                self.last_command_after_wake = command_after_wake
                voice_event(
                    "wake_included_command",
                    heard=heard,
                    command=command_after_wake,
                )

        return self._accept_match(match, "final")
