import json
import queue
import time

from vosk import KaldiRecognizer

from audio_runtime import audio_queue, clear_audio_queue
from config import MAX_COMMAND_SECONDS, SAMPLE_RATE, WAKE_WORDS
from wake import WakeWordInterrupted, has_wake_word


def remove_wake_words(text: str) -> str:
    cleaned = text.lower().strip()
    for wake in WAKE_WORDS:
        cleaned = cleaned.replace(wake, " ")
    return " ".join(cleaned.split())


def listen_for_command(model, seconds: int = MAX_COMMAND_SECONDS, allow_wake_interrupt: bool = True) -> str:
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)

    clear_audio_queue()

    start = time.time()
    last_speech_time = time.time()
    last_partial = ""
    final_parts = []

    print("Listening for command...")

    while time.time() - start < seconds:
        try:
            data = audio_queue.get(timeout=0.5)
        except queue.Empty:
            continue

        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            text = result.get("text", "").strip()

            if text:
                if allow_wake_interrupt and has_wake_word(text):
                    command_after_wake = remove_wake_words(text)
                    if command_after_wake:
                        return command_after_wake
                    raise WakeWordInterrupted()

                final_parts.append(text)
                last_speech_time = time.time()
                print("final part:", text)
        else:
            partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()

            if partial and partial != last_partial:
                print("partial:", partial)
                last_partial = partial
                last_speech_time = time.time()

                if allow_wake_interrupt and has_wake_word(partial):
                    raise WakeWordInterrupted()

        if final_parts and time.time() - last_speech_time > 0.7:
            break

    final = json.loads(recognizer.FinalResult()).get("text", "").strip()

    if final:
        final_parts.append(final)

    if not final_parts and last_partial:
        return last_partial

    return " ".join(final_parts).strip()
