import json
import queue
import time

from vosk import KaldiRecognizer

from config import LENIENT_WAKE_PARTIALS, MAX_COMMAND_SECONDS, SAMPLE_RATE, WAKE_WORDS
from detect_wake_word import has_wake_word
from interruptions import WakeWordInterrupted
from listen_to_mic import audio_queue, clear_audio_queue, open_microphone_stream


def remove_wake_words(text: str) -> str:
    cleaned = text.lower().strip()
    wake_phrases = sorted(
        [*WAKE_WORDS, *LENIENT_WAKE_PARTIALS],
        key=len,
        reverse=True,
    )
    for wake in wake_phrases:
        cleaned = cleaned.replace(wake, " ")
    return " ".join(cleaned.split())


def listen_for_command(model, seconds: int = MAX_COMMAND_SECONDS, allow_wake_interrupt: bool = True) -> str:
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)

    clear_audio_queue()

    start = time.time()
    last_speech_time = time.time()
    last_partial = ""
    final_parts = []
    stop_reason = "listen window expired"

    print(f"Listening for command for up to {seconds} seconds...")

    with open_microphone_stream():
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
                            elapsed = time.time() - start
                            print(
                                f"Stopped listening after {elapsed:.1f}s: "
                                "wake phrase included command."
                            )
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
                stop_reason = "speech followed by 0.7s silence"
                break

    final = json.loads(recognizer.FinalResult()).get("text", "").strip()

    if final:
        final_parts.append(final)

    elapsed = time.time() - start

    if not final_parts and last_partial:
        print(
            f"Stopped listening after {elapsed:.1f}s: "
            f"{stop_reason}; using partial transcript."
        )
        return last_partial

    command = " ".join(final_parts).strip()
    if command:
        print(f"Stopped listening after {elapsed:.1f}s: {stop_reason}.")
    else:
        print(f"Stopped listening after {elapsed:.1f}s: no speech heard.")

    return command
