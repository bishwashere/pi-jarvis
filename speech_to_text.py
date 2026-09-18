import os
import json
import queue
import subprocess
import sys
import time
import wave
from array import array

from vosk import KaldiRecognizer

from config import (
    COMMAND_AUDIO_RMS_THRESHOLD,
    COMMAND_MIN_RECORD_SECONDS,
    COMMAND_RECORDING_PATH,
    COMMAND_SILENCE_SECONDS,
    COMMAND_STT_ENGINE,
    MAX_COMMAND_SECONDS,
    SAMPLE_RATE,
    WAKE_WORDS,
    WHISPER_CPP_BINARY,
    WHISPER_MODEL_PATH,
    WHISPER_THREADS,
    WHISPER_TIMEOUT_SECONDS,
)
from detect_wake_word import has_strict_wake_word
from listen_to_mic import audio_queue, clear_audio_queue, open_microphone_stream
from voice_log import voice_event


WAKE_ONLY_COMMAND = "__jarvis_wake_only__"


NON_COMMAND_CUE_WORDS = {
    "ambient",
    "applause",
    "audio",
    "background",
    "blank",
    "clapping",
    "dramatic",
    "instrumental",
    "intro",
    "laugh",
    "laughing",
    "laughter",
    "music",
    "noise",
    "noises",
    "outro",
    "playing",
    "silence",
    "sound",
    "sounds",
    "upbeat",
}

NON_COMMAND_EXACT_PHRASES = {
    "background music",
    "background noise",
    "blank audio",
    "dramatic music",
    "instrumental music",
    "music",
    "music playing",
    "no command",
    "noise",
    "silence",
    "sound",
    "sounds",
}


def is_only_bracketed_cues(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    while stripped:
        stripped = stripped.strip()
        if not stripped:
            return True

        opener = stripped[0]
        closer = {"[": "]", "(": ")"}.get(opener)
        if closer is None:
            return False

        end = stripped.find(closer, 1)
        if end < 0:
            return False

        content = stripped[1:end].strip()
        if not content:
            return False

        stripped = stripped[end + 1 :]

    return True


def normalize_transcript(text: str) -> str:
    cleaned = text.lower().strip()
    cleaned = cleaned.replace("[", " ").replace("]", " ")
    cleaned = cleaned.replace("(", " ").replace(")", " ")
    cleaned = cleaned.replace("{", " ").replace("}", " ")
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
    return " ".join(cleaned.split())


def is_non_command_transcript(text: str) -> bool:
    if is_only_bracketed_cues(text):
        return True

    normalized = normalize_transcript(text)
    if not normalized:
        return True

    if normalized in NON_COMMAND_EXACT_PHRASES:
        return True

    words = normalized.split()
    return all(word in NON_COMMAND_CUE_WORDS for word in words)


def clean_command_transcript(text: str) -> str:
    if is_non_command_transcript(text):
        voice_event("transcript_ignored", reason="non_command", text=text)
        print(f"Ignoring non-command transcript: {text!r}", flush=True)
        return ""

    normalized = normalize_transcript(text)
    command = remove_wake_words(normalized)
    if has_strict_wake_word(normalized) and not command:
        voice_event("transcript_wake_only", text=text)
        return WAKE_ONLY_COMMAND

    voice_event("transcript_accepted", command=command)
    return command


def remove_wake_words(text: str) -> str:
    cleaned = normalize_transcript(text)
    wake_phrases = sorted(
        [wake.split() for wake in WAKE_WORDS],
        key=lambda words: len(words),
        reverse=True,
    )

    words = cleaned.split()
    output = []
    index = 0
    while index < len(words):
        matched_length = 0
        for wake_words in wake_phrases:
            if words[index : index + len(wake_words)] == wake_words:
                matched_length = len(wake_words)
                break

        if matched_length:
            index += matched_length
            continue

        output.append(words[index])
        index += 1

    return " ".join(output)


def handle_wake_phrase_during_command(text: str, start: float) -> str | None:
    if not has_strict_wake_word(text):
        return None

    command_after_wake = remove_wake_words(text)
    elapsed = time.time() - start

    if command_after_wake:
        print(
            f"Stopped listening after {elapsed:.1f}s: "
            "wake phrase included command."
        )
        return command_after_wake

    print(
        f"Wake phrase heard during command listening after {elapsed:.1f}s; "
        "waiting for command.",
        flush=True,
    )
    return ""


def calculate_rms(data: bytes) -> float:
    if len(data) < 2:
        return 0.0

    samples = array("h")
    samples.frombytes(data[: len(data) - (len(data) % 2)])
    if sys.byteorder == "big":
        samples.byteswap()

    if not samples:
        return 0.0

    square_sum = sum(sample * sample for sample in samples)
    return (square_sum / len(samples)) ** 0.5


def write_wav(path: str, frames: list[bytes]):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"".join(frames))


def record_command_audio(seconds: int) -> str:
    clear_audio_queue()

    start = time.time()
    last_voice_time = None
    speech_started = False
    frames = []
    peak_rms = 0.0
    stop_reason = "recording window expired"

    voice_event("audio_recording_started", seconds=seconds)
    print(f"Recording command audio for up to {seconds} seconds...")

    with open_microphone_stream():
        while time.time() - start < seconds:
            try:
                data = audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            frames.append(data)
            rms = calculate_rms(data)
            peak_rms = max(peak_rms, rms)

            if rms >= COMMAND_AUDIO_RMS_THRESHOLD:
                if not speech_started:
                    voice_event(
                        "audio_speech_started",
                        after_seconds=f"{time.time() - start:.1f}",
                        rms=f"{rms:.0f}",
                        threshold=COMMAND_AUDIO_RMS_THRESHOLD,
                    )
                    print(
                        f"Whisper command recording detected speech "
                        f"after {time.time() - start:.1f}s "
                        f"(rms={rms:.0f}).",
                        flush=True,
                    )
                speech_started = True
                last_voice_time = time.time()

            if (
                speech_started
                and last_voice_time is not None
                and time.time() - last_voice_time >= COMMAND_SILENCE_SECONDS
                and time.time() - start >= COMMAND_MIN_RECORD_SECONDS
            ):
                stop_reason = (
                    f"speech followed by {COMMAND_SILENCE_SECONDS:.1f}s silence"
                )
                break

    elapsed = time.time() - start
    if not speech_started:
        voice_event(
            "audio_recording_finished",
            reason="no_speech",
            elapsed_seconds=f"{elapsed:.1f}",
            peak_rms=f"{peak_rms:.0f}",
        )
        print(
            f"Stopped recording after {elapsed:.1f}s: "
            f"no speech heard (peak rms={peak_rms:.0f}).",
            flush=True,
        )
        return ""

    voice_event(
        "audio_recording_finished",
        reason=stop_reason,
        elapsed_seconds=f"{elapsed:.1f}",
        peak_rms=f"{peak_rms:.0f}",
    )
    write_wav(COMMAND_RECORDING_PATH, frames)
    return COMMAND_RECORDING_PATH


def transcribe_with_whisper(audio_path: str) -> str:
    if not audio_path:
        return ""

    start = time.time()

    try:
        result = subprocess.run(
            [
                WHISPER_CPP_BINARY,
                "-m",
                WHISPER_MODEL_PATH,
                "-f",
                audio_path,
                "-nt",
                "-np",
                "-t",
                str(WHISPER_THREADS),
            ],
            capture_output=True,
            text=True,
            timeout=WHISPER_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as e:
        print(f"Whisper executable not found: {e}", flush=True)
        return ""
    except subprocess.TimeoutExpired:
        print(
            f"Whisper timed out after {WHISPER_TIMEOUT_SECONDS}s.",
            flush=True,
        )
        return ""

    elapsed = time.time() - start
    if result.returncode != 0:
        print(
            f"Whisper failed after {elapsed:.1f}s "
            f"(exit {result.returncode}): {result.stderr.strip()}",
            flush=True,
        )
        return ""

    transcript = " ".join(result.stdout.split()).strip()
    voice_event(
        "whisper_transcript",
        elapsed_seconds=f"{elapsed:.1f}",
        text=transcript,
    )
    print(f"Whisper transcript after {elapsed:.1f}s: {transcript!r}", flush=True)
    return clean_command_transcript(transcript)


def listen_for_command_with_whisper(seconds: int) -> str:
    voice_event("command_listen_started", engine="whisper", seconds=seconds)
    print(f"Listening for command with Whisper for up to {seconds} seconds...")
    deadline = time.time() + seconds

    while time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        audio_path = record_command_audio(remaining)
        if not audio_path:
            return ""

        command = transcribe_with_whisper(audio_path)
        if command:
            return command

        if time.time() < deadline:
            voice_event("command_listen_continued", reason="ignored_or_empty_transcript")
            print(
                "No command in captured audio; still listening.",
                flush=True,
            )

    return ""


def listen_for_command(model, seconds: int = MAX_COMMAND_SECONDS, allow_wake_interrupt: bool = True) -> str:
    if COMMAND_STT_ENGINE.lower() == "whisper":
        return listen_for_command_with_whisper(seconds)

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
                    if allow_wake_interrupt:
                        command_after_wake = handle_wake_phrase_during_command(
                            text,
                            start,
                        )
                        if command_after_wake is not None:
                            if command_after_wake:
                                return command_after_wake
                            continue

                    final_parts.append(text)
                    last_speech_time = time.time()
                    print("final part:", text)
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "").strip()

                if partial and partial != last_partial:
                    print("partial:", partial)
                    last_partial = partial
                    last_speech_time = time.time()

                    if allow_wake_interrupt and has_strict_wake_word(partial):
                        handle_wake_phrase_during_command(partial, start)
                        continue

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
        return clean_command_transcript(last_partial)

    command = " ".join(final_parts).strip()
    if command:
        print(f"Stopped listening after {elapsed:.1f}s: {stop_reason}.")
    else:
        print(f"Stopped listening after {elapsed:.1f}s: no speech heard.")

    return clean_command_transcript(command)
