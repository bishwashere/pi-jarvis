import random
import time

import requests
from vosk import Model

from call_agent_api import ask_pasture, check_agent_health, start_new_pasture_session
from config import (
    API_RETRY_COUNT,
    CHECKING_REPLIES,
    COMMAND_RETRY_COUNT,
    FOLLOWUP_SECONDS,
    GENERIC_ERROR_REPLY,
    LENIENT_WAKE_LEVEL,
    MAX_COMMAND_SECONDS,
    STANDBY_REPLIES,
    VOSK_MODEL_PATH,
    WAKE_REPLIES,
    WAKE_WORDS,
)
from detect_wake_word import WakeWordMonitor
from interruptions import WakeWordInterrupted, wait_for_result_or_wake_word
from listen_to_mic import (
    audio_queue,
    clear_audio_queue,
    open_microphone_stream,
    reset_audio_device_selection,
)
from play_audio import play_online_tone, play_wav_file
from speech_to_text import listen_for_command
from text_to_speech import synthesize_to_wav


END_SESSION_PHRASES = {
    "bye",
    "bye jarvis",
    "cancel",
    "cancel jarvis",
    "do nothing",
    "do nothing jarvis",
    "good bye",
    "good bye jarvis",
    "goodbye",
    "goodbye jarvis",
    "nevermind",
    "nevermind jarvis",
    "never mind",
    "never mind jarvis",
    "no command",
    "no command jarvis",
    "nothing",
    "nothing jarvis",
    "stop",
    "stop jarvis",
}


def normalize_command(text: str) -> str:
    cleaned = text.lower().strip()
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
    return " ".join(cleaned.split())


def is_end_session_command(text: str) -> bool:
    return normalize_command(text) in END_SESSION_PHRASES


def end_pasture_session_quietly():
    if not start_new_pasture_session():
        print("Could not reset Pasture session; returning to wake word mode.", flush=True)


def speak(text: str, model=None):
    path = synthesize_to_wav(text)
    play_wav_file(path)


def confirm_standby_if_served(served_turn: bool, model):
    if served_turn:
        speak(random.choice(STANDBY_REPLIES), model=model)


def get_command_with_retries(model) -> str:
    for attempt in range(COMMAND_RETRY_COUNT):
        try:
            command = listen_for_command(model, seconds=MAX_COMMAND_SECONDS)
        except WakeWordInterrupted:
            print(
                "Wake phrase interrupted command listening; continuing quietly.",
                flush=True,
            )
            continue

        if command:
            return command

        if attempt < COMMAND_RETRY_COUNT - 1:
            print("No command heard. Listening again.", flush=True)

    return ""


def get_followup_until(model, seconds: int) -> str:
    deadline = time.time() + seconds

    while time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        try:
            followup = listen_for_command(model, seconds=remaining)
        except WakeWordInterrupted:
            raise

        if followup:
            return followup

        if time.time() < deadline:
            print(
                "No follow-up command heard yet; still waiting.",
                flush=True,
            )

    return ""


def ask_and_speak(user_text: str, model) -> bool:
    for attempt in range(API_RETRY_COUNT):
        try:
            result = wait_for_result_or_wake_word(
                ask_pasture,
                model,
                user_text,
                on_wait_start=(
                    lambda: speak(random.choice(CHECKING_REPLIES), model=model)
                    if attempt == 0
                    else None
                ),
            )

            reply = result.get("reply", "")
            continue_listening = bool(result.get("continue_listening", False))

            speak(reply, model=model)
            return continue_listening

        except WakeWordInterrupted:
            print("Wake phrase interrupted API/playback; listening for command.", flush=True)
            raise

        except requests.exceptions.RequestException as e:
            print("API error:", e)

            if attempt < API_RETRY_COUNT - 1:
                print("Retrying Pasture request silently.", flush=True)
                continue

            print("Pasture request failed after retries; returning to wake word mode.", flush=True)
            return None

        except Exception as e:
            print("Unexpected error:", e)
            speak(GENERIC_ERROR_REPLY, model=model)
            return True

    return True


def handle_conversation(model):
    clear_audio_queue()
    speak(random.choice(WAKE_REPLIES))
    served_turn = False

    command = get_command_with_retries(model)

    if not command:
        print("No command heard after wake. Returning to wake word mode.", flush=True)
        return

    while command:
        if is_end_session_command(command):
            print("End-session command heard. Returning to wake word mode.", flush=True)
            end_pasture_session_quietly()
            confirm_standby_if_served(served_turn, model)
            return

        print("Command:", command)

        try:
            should_continue = ask_and_speak(command, model)
        except WakeWordInterrupted:
            command = get_command_with_retries(model)
            continue

        if should_continue is None:
            return

        served_turn = True

        while True:
            listen_seconds = MAX_COMMAND_SECONDS if should_continue else FOLLOWUP_SECONDS
            listen_started_at = time.time()

            try:
                followup = get_followup_until(model, listen_seconds)
            except WakeWordInterrupted:
                print(
                    "Wake phrase interrupted follow-up listening; listening for command.",
                    flush=True,
                )
                command = get_command_with_retries(model)
                break

            if not followup:
                elapsed = time.time() - listen_started_at
                print(
                    f"No follow-up after {elapsed:.1f}s "
                    f"(listen window: {listen_seconds}s). "
                    "Returning to wake word mode."
                )
                confirm_standby_if_served(served_turn, model)
                command = ""
                break

            if is_end_session_command(followup):
                print("End-session follow-up heard. Returning to wake word mode.", flush=True)
                end_pasture_session_quietly()
                confirm_standby_if_served(served_turn, model)
                command = ""
                return

            print("Follow-up:", followup)

            try:
                should_continue = ask_and_speak(followup, model)
            except WakeWordInterrupted:
                command = get_command_with_retries(model)
                break

            if should_continue is None:
                return

            served_turn = True
            command = ""


def run_assistant():
    print("Loading Vosk model...")
    model = Model(VOSK_MODEL_PATH)
    wake_monitor = WakeWordMonitor(model)

    print("Jarvis voice loop running.")
    print(f'Say one of these to wake: {", ".join(WAKE_WORDS)}')
    print(f"Lenient wake level: {LENIENT_WAKE_LEVEL}")
    print("Press Ctrl+C to stop.")

    try:
        check_agent_health()
        print("Jarvis agent health check passed; playing online tone.")
        play_online_tone()
    except Exception as e:
        print("Jarvis agent health check failed:", e)

    while True:
        print("Waiting for wake word...", flush=True)
        try:
            with open_microphone_stream():
                while True:
                    data = audio_queue.get()

                    if wake_monitor.accept_audio(data):
                        clear_audio_queue()
                        break
        except Exception as e:
            print(f"Microphone stream failed: {e}. Retrying in 5 seconds.", flush=True)
            reset_audio_device_selection()
            time.sleep(5)
            continue

        handle_conversation(model)
        clear_audio_queue()
        wake_monitor.reset()
