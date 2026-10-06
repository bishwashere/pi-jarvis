import random
import queue
import threading
import time

import requests

from call_agent_api import ask_pasture, check_agent_health, start_new_pasture_session
from config import (
    API_RETRY_COUNT,
    CHECKING_REPLY_DELAY_SECONDS,
    CHECKING_REPLIES,
    COMMAND_SERVER_ENABLED,
    COMMAND_RETRY_COUNT,
    FOLLOWUP_SECONDS,
    GENERIC_ERROR_REPLY,
    LENIENT_WAKE_LEVEL,
    MAX_COMMAND_SECONDS,
    STAND_DOWN_SECONDS,
    STANDBY_REPLIES,
    STILL_CHECKING_REPLIES,
    STILL_CHECKING_REPLY_DELAY_SECONDS,
    UNCLEAR_FOLLOWUP_REPLIES,
    VOSK_MODEL_PATH,
    WAKE_REPLIES,
    WAKE_WORDS,
)
from daily_context import (
    choose_wake_reply,
    contextualize_affirmative_command,
    maybe_refresh_context_bucket_async,
    record_utterance,
)
from detect_wake_word import WakeWordMonitor
from interruptions import WakeWordInterrupted, wait_for_result_or_wake_word
from jarvis_command_server import start_command_server
from listen_to_mic import (
    audio_queue,
    clear_audio_queue,
    open_microphone_stream,
    reset_audio_device_selection,
)
from play_audio import (
    play_command_captured_tone,
    play_command_server_chime,
    play_online_tone,
    play_wav_file,
)
from speech_to_text import WAKE_ONLY_COMMAND, listen_for_command
from text_to_speech import synthesize_to_wav
from voice_log import voice_event


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

STAND_DOWN_PHRASES = {
    "jarvis stand down",
    "stand down",
    "stand down for an hour",
    "stand down for one hour",
}


_speak_lock = threading.Lock()
_local_command_queue = queue.Queue()
_stand_down_until = 0.0


def normalize_command(text: str) -> str:
    cleaned = text.lower().strip()
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
    return " ".join(cleaned.split())


def is_end_session_command(text: str) -> bool:
    return normalize_command(text) in END_SESSION_PHRASES


def is_wake_only_command(text: str) -> bool:
    return text == WAKE_ONLY_COMMAND


def is_stand_down_command(text: str) -> bool:
    return normalize_command(text) in STAND_DOWN_PHRASES


def stand_down_remaining(now: float | None = None) -> float:
    current_time = time.time() if now is None else now
    return max(0.0, _stand_down_until - current_time)


def is_standing_down(now: float | None = None) -> bool:
    return stand_down_remaining(now) > 0


def start_stand_down(seconds: int = STAND_DOWN_SECONDS) -> float:
    global _stand_down_until
    _stand_down_until = time.time() + seconds
    voice_event(
        "stand_down_started",
        seconds=seconds,
        until=time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(_stand_down_until)),
    )
    return _stand_down_until


def handle_stand_down_command(model) -> bool:
    start_stand_down()
    speak("Standing down for one hour.", model=model, kind="stand_down")
    return False


def end_pasture_session_quietly():
    if not start_new_pasture_session():
        print("Could not reset Pasture session; returning to wake word mode.", flush=True)


def speak(text: str, model=None, kind: str = "speech"):
    voice_event("spoken", kind=kind, text=text)
    with _speak_lock:
        path = synthesize_to_wav(text)
        play_wav_file(path)


def speak_wake_reply(model=None) -> str | None:
    reply, source = choose_wake_reply(WAKE_REPLIES)
    voice_event("wake_reply_selected", source=source, text=reply)
    speak(reply, model=model, kind="wake_reply")
    return reply if source == "daily-context" else None


def confirm_standby_if_served(served_turn: bool, model):
    if served_turn:
        speak(random.choice(STANDBY_REPLIES), model=model, kind="standby")


def confirm_command_captured():
    try:
        voice_event("command_captured_tone")
        play_command_captured_tone()
    except Exception as e:
        print("Command captured tone failed:", e, flush=True)


def play_command_server_preamble():
    try:
        voice_event("command_server_chime")
        play_command_server_chime()
    except Exception as e:
        print("Command server chime failed:", e, flush=True)


def get_command_with_retries(model) -> str:
    for attempt in range(COMMAND_RETRY_COUNT):
        voice_event(
            "command_listen_attempt",
            kind="initial",
            attempt=attempt + 1,
            seconds=MAX_COMMAND_SECONDS,
        )
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
    clarified_unclear_audio = False

    def clarify_unclear_audio():
        nonlocal clarified_unclear_audio
        if clarified_unclear_audio:
            return

        clarified_unclear_audio = True
        voice_event("followup_unclear_audio")
        speak(random.choice(UNCLEAR_FOLLOWUP_REPLIES), model=model, kind="clarification")

    while time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        voice_event("command_listen_attempt", kind="followup", seconds=remaining)
        try:
            followup = listen_for_command(
                model,
                seconds=remaining,
                on_unclear_audio=clarify_unclear_audio,
            )
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


def ask_and_speak(user_text: str, model, *, announce_waiting: bool = True) -> bool:
    for attempt in range(API_RETRY_COUNT):
        try:
            started_at = time.time()
            voice_event(
                "pasture_request_started",
                attempt=attempt + 1,
                text=user_text,
            )
            result = wait_for_result_or_wake_word(
                ask_pasture,
                model,
                user_text,
                on_wait_start=(
                    (lambda: speak(random.choice(CHECKING_REPLIES), model=model, kind="checking"))
                    if announce_waiting and attempt == 0 else None
                ),
                on_wait_start_delay=CHECKING_REPLY_DELAY_SECONDS,
                on_still_waiting=(
                    (lambda: speak(random.choice(STILL_CHECKING_REPLIES), model=model, kind="still_checking"))
                    if announce_waiting and attempt == 0 else None
                ),
                on_still_waiting_delay=STILL_CHECKING_REPLY_DELAY_SECONDS,
            )

            reply = result.get("reply", "")
            continue_listening = bool(result.get("continue_listening", False))
            voice_event(
                "pasture_response_received",
                elapsed_seconds=f"{time.time() - started_at:.1f}",
                continue_listening=continue_listening,
                reply_chars=len(reply),
            )

            speak(reply, model=model, kind="answer")
            return continue_listening

        except WakeWordInterrupted:
            print("Wake phrase interrupted API/playback; listening for command.", flush=True)
            raise

        except requests.exceptions.RequestException as e:
            voice_event("pasture_request_failed", attempt=attempt + 1, error=e)
            print("API error:", e)

            if attempt < API_RETRY_COUNT - 1:
                print("Retrying Pasture request silently.", flush=True)
                continue

            print("Pasture request failed after retries; returning to wake word mode.", flush=True)
            return None

        except Exception as e:
            voice_event("unexpected_error", error=e)
            print("Unexpected error:", e)
            speak(GENERIC_ERROR_REPLY, model=model, kind="error")
            return True

    return True


def prepare_command_for_api(command: str, wake_context_prompt: str | None, kind: str) -> str:
    api_text = contextualize_affirmative_command(command, wake_context_prompt)
    voice_event("command_prepared", kind=kind, text=api_text)
    record_utterance(api_text, kind=kind)
    return api_text


def handle_local_command(payload: dict) -> dict:
    raw_command = str(payload.get("command") or payload.get("action") or "")
    command = normalize_command(raw_command.replace("_", " "))
    text = str(
        payload.get("text")
        or payload.get("instruction")
        or payload.get("message")
        or ""
    ).strip()
    voice_event("command_server_received", command=command, text=text)

    if command == "status":
        return {"ok": True, "status": "running"}

    if command in {"", "speak", "say"}:
        if not text:
            return {"ok": False, "error": "text, instruction, or message is required"}

        _local_command_queue.put({"text": text})
        voice_event("command_server_queued", text=text)
        return {"ok": True, "queued": True, "text": text}

    return {"ok": False, "error": f"unknown command: {command}"}


def process_command_loop(
    model,
    command: str,
    served_turn: bool = False,
    wake_context_prompt: str | None = None,
    quiet_first_response: bool = False,
):
    while command:
        if is_wake_only_command(command):
            voice_event("wake_only_command", kind="initial")
            print("Wake-only command heard; repeating wake prompt.", flush=True)
            wake_context_prompt = speak_wake_reply(model=model)
            command = get_command_with_retries(model)
            if not command:
                voice_event("command_listen_finished", result="no_command_after_wake_only")
                print("No command heard after wake. Returning to wake word mode.", flush=True)
                return
            continue

        if is_end_session_command(command):
            voice_event("session_end_command", kind="initial", text=command)
            print("End-session command heard. Returning to wake word mode.", flush=True)
            end_pasture_session_quietly()
            confirm_standby_if_served(served_turn, model)
            return

        if is_stand_down_command(command):
            confirm_command_captured()
            voice_event("stand_down_command", kind="initial", text=command)
            handle_stand_down_command(model)
            return

        confirm_command_captured()
        voice_event("command_accepted", kind="initial", text=command)
        print("Command:", command)
        command_for_api = prepare_command_for_api(
            command,
            wake_context_prompt,
            kind="command",
        )
        wake_context_prompt = None

        try:
            should_continue = ask_and_speak(
                command_for_api,
                model,
                announce_waiting=not quiet_first_response,
            )
            maybe_refresh_context_bucket_async()
        except WakeWordInterrupted:
            command = get_command_with_retries(model)
            continue

        quiet_first_response = False

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
                voice_event(
                    "followup_listen_finished",
                    result="no_followup",
                    elapsed_seconds=f"{elapsed:.1f}",
                    seconds=listen_seconds,
                )
                print(
                    f"No follow-up after {elapsed:.1f}s "
                    f"(listen window: {listen_seconds}s). "
                    "Returning to wake word mode."
                )
                confirm_standby_if_served(served_turn, model)
                command = ""
                break

            if is_end_session_command(followup):
                voice_event("session_end_command", kind="followup", text=followup)
                print("End-session follow-up heard. Returning to wake word mode.", flush=True)
                end_pasture_session_quietly()
                confirm_standby_if_served(served_turn, model)
                command = ""
                return

            if is_wake_only_command(followup):
                voice_event("wake_only_command", kind="followup")
                print("Wake-only follow-up heard; repeating wake prompt.", flush=True)
                wake_context_prompt = speak_wake_reply(model=model)
                command = get_command_with_retries(model)
                break

            if is_stand_down_command(followup):
                confirm_command_captured()
                voice_event("stand_down_command", kind="followup", text=followup)
                handle_stand_down_command(model)
                command = ""
                return

            confirm_command_captured()
            voice_event("command_accepted", kind="followup", text=followup)
            print("Follow-up:", followup)
            followup_for_api = prepare_command_for_api(
                followup,
                wake_context_prompt,
                kind="followup",
            )
            wake_context_prompt = None

            try:
                should_continue = ask_and_speak(followup_for_api, model)
                maybe_refresh_context_bucket_async()
            except WakeWordInterrupted:
                command = get_command_with_retries(model)
                break

            if should_continue is None:
                return

            served_turn = True
            command = ""


def handle_conversation(model):
    clear_audio_queue()
    wake_context_prompt = speak_wake_reply(model=model)

    command = get_command_with_retries(model)

    if not command:
        voice_event("command_listen_finished", result="no_initial_command")
        print("No command heard after wake. Returning to wake word mode.", flush=True)
        return

    process_command_loop(
        model,
        command,
        served_turn=False,
        wake_context_prompt=wake_context_prompt,
    )


def get_pending_local_command():
    try:
        return _local_command_queue.get_nowait()
    except queue.Empty:
        return None


def handle_command_server_instruction(model, payload: dict):
    text = str(payload.get("text") or "").strip()
    if not text:
        return

    clear_audio_queue()
    voice_event("command_server_instruction_started", text=text)
    play_command_server_preamble()
    speak(text, model=model, kind="command_server")

    try:
        command = get_command_with_retries(model)
    except WakeWordInterrupted:
        print("Wake phrase interrupted command-server command listening; listening again.", flush=True)
        command = get_command_with_retries(model)

    if not command:
        voice_event("command_listen_finished", result="no_command_after_command_server")
        return

    process_command_loop(
        model,
        command,
        served_turn=False,
        wake_context_prompt=None,
        quiet_first_response=True,
    )


def run_assistant():
    from vosk import Model

    print("Loading Vosk model...")
    model = Model(VOSK_MODEL_PATH)
    wake_monitor = WakeWordMonitor(model)

    print("Jarvis voice loop running.")
    print(f'Say one of these to wake: {", ".join(WAKE_WORDS)}')
    print(f"Lenient wake level: {LENIENT_WAKE_LEVEL}")
    print("Press Ctrl+C to stop.")

    try:
        check_agent_health()
        voice_event("health_check_passed")
        print("Jarvis agent health check passed; playing online tone.")
        play_online_tone()
    except Exception as e:
        voice_event("health_check_failed", error=e)
        print("Jarvis agent health check failed:", e)

    if COMMAND_SERVER_ENABLED:
        try:
            start_command_server(handle_local_command)
        except Exception as e:
            voice_event("command_server_failed", error=e)
            print("Jarvis command server failed:", e, flush=True)

    while True:
        pending_command = get_pending_local_command()
        if pending_command:
            handle_command_server_instruction(model, pending_command)
            clear_audio_queue()
            wake_monitor.reset()
            continue

        remaining_stand_down = stand_down_remaining()
        if remaining_stand_down > 0:
            time.sleep(min(1.0, remaining_stand_down))
            continue

        voice_event("wake_listen_started")
        print("Waiting for wake word...", flush=True)
        pending_command = None
        wake_heard = False
        try:
            with open_microphone_stream():
                while True:
                    pending_command = get_pending_local_command()
                    if pending_command:
                        clear_audio_queue()
                        break

                    try:
                        data = audio_queue.get(timeout=0.2)
                    except queue.Empty:
                        continue

                    if wake_monitor.accept_audio(data):
                        clear_audio_queue()
                        wake_heard = True
                        break
        except Exception as e:
            print(f"Microphone stream failed: {e}. Retrying in 5 seconds.", flush=True)
            reset_audio_device_selection()
            time.sleep(5)
            continue

        if pending_command:
            handle_command_server_instruction(model, pending_command)
        elif wake_heard:
            command_after_wake = wake_monitor.last_command_after_wake
            if command_after_wake:
                process_command_loop(
                    model,
                    command_after_wake,
                    served_turn=False,
                    wake_context_prompt=None,
                )
            else:
                handle_conversation(model)

        clear_audio_queue()
        wake_monitor.reset()
