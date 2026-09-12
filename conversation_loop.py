import requests
from vosk import Model

from call_agent_api import ask_pasture, check_agent_health
from config import (
    API_ERROR_REPLY,
    API_RETRY_COUNT,
    API_RETRY_REPLY,
    COMMAND_FAILED_REPLY,
    COMMAND_RETRY_COUNT,
    DID_NOT_CATCH_REPLY,
    FOLLOWUP_SECONDS,
    GENERIC_ERROR_REPLY,
    HEALTH_ERROR_REPLY,
    HEALTH_OK_REPLY,
    LENIENT_WAKE_PARTIALS,
    LISTEN_AGAIN_REPLY,
    MAX_COMMAND_SECONDS,
    VOSK_MODEL_PATH,
    WAKE_REPLY,
    WAKE_WORDS,
)
from detect_wake_word import WakeWordMonitor
from interruptions import WakeWordInterrupted, wait_for_result_or_wake_word
from listen_to_mic import audio_queue, clear_audio_queue, open_microphone_stream
from play_audio import play_wav_file
from speech_to_text import listen_for_command
from text_to_speech import synthesize_to_wav


def speak(text: str, model=None):
    path = synthesize_to_wav(text)
    play_wav_file(path)


def get_command_with_retries(model) -> str:
    for attempt in range(COMMAND_RETRY_COUNT):
        try:
            command = listen_for_command(model, seconds=MAX_COMMAND_SECONDS)
        except WakeWordInterrupted:
            speak(LISTEN_AGAIN_REPLY, model=model)
            continue

        if command:
            return command

        if attempt < COMMAND_RETRY_COUNT - 1:
            speak(COMMAND_FAILED_REPLY, model=model)

    return ""


def ask_and_speak(user_text: str, model) -> bool:
    for attempt in range(API_RETRY_COUNT):
        try:
            result = wait_for_result_or_wake_word(ask_pasture, model, user_text)

            reply = result.get("reply", "")
            continue_listening = bool(result.get("continue_listening", False))

            speak(reply, model=model)
            return continue_listening

        except WakeWordInterrupted:
            speak(LISTEN_AGAIN_REPLY, model=model)
            raise

        except requests.exceptions.RequestException as e:
            print("API error:", e)

            if attempt < API_RETRY_COUNT - 1:
                speak(API_RETRY_REPLY, model=model)
                continue

            speak(API_ERROR_REPLY, model=model)
            return True

        except Exception as e:
            print("Unexpected error:", e)
            speak(GENERIC_ERROR_REPLY, model=model)
            return True

    return True


def handle_conversation(model):
    clear_audio_queue()
    speak(WAKE_REPLY)

    command = get_command_with_retries(model)

    if not command:
        speak(DID_NOT_CATCH_REPLY, model=model)
        return

    while command:
        print("Command:", command)

        try:
            should_continue = ask_and_speak(command, model)
        except WakeWordInterrupted:
            command = get_command_with_retries(model)
            continue

        while True:
            listen_seconds = MAX_COMMAND_SECONDS if should_continue else FOLLOWUP_SECONDS

            try:
                followup = listen_for_command(model, seconds=listen_seconds)
            except WakeWordInterrupted:
                speak(LISTEN_AGAIN_REPLY, model=model)
                command = get_command_with_retries(model)
                break

            if not followup:
                print("No follow-up. Returning to wake word mode.")
                command = ""
                break

            print("Follow-up:", followup)

            try:
                should_continue = ask_and_speak(followup, model)
            except WakeWordInterrupted:
                speak(LISTEN_AGAIN_REPLY, model=model)
                command = get_command_with_retries(model)
                break

            command = ""


def run_assistant():
    print("Loading Vosk model...")
    model = Model(VOSK_MODEL_PATH)
    wake_monitor = WakeWordMonitor(model)

    print("Jarvis voice loop running.")
    print(f'Say one of these to wake: {", ".join(WAKE_WORDS)}')
    print(f'Lenient wake partials: {", ".join(LENIENT_WAKE_PARTIALS)}')
    print("Press Ctrl+C to stop.")

    try:
        check_agent_health()
        print("Jarvis agent health check passed.")
        speak(HEALTH_OK_REPLY)
    except Exception as e:
        print("Jarvis agent health check failed:", e)
        speak(HEALTH_ERROR_REPLY)

    while True:
        with open_microphone_stream():
            while True:
                data = audio_queue.get()

                if wake_monitor.accept_audio(data):
                    clear_audio_queue()
                    break

        handle_conversation(model)
        clear_audio_queue()
        wake_monitor.reset()
