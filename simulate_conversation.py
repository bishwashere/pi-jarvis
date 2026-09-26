"""Scripted end-to-end conversation simulation for Pi Jarvis.

This exercises the normal wake -> command -> API response conversation path
without opening the microphone or speaker. Scripted utterances are synthesized
to WAV, transcribed through the configured STT engine, and replies are
synthesized then muted for their WAV duration.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
import wave
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator

import conversation_loop
from config import RUNTIME_DIR
from detect_wake_word import get_wake_match
from speech_to_text import WAKE_ONLY_COMMAND, clean_command_transcript, transcribe_audio_file
from voice_log import voice_event


SIMULATION_AUDIO_DIR = RUNTIME_DIR / "cache/simulations"


@dataclass
class SimulationOptions:
    utterances: list[str]
    fake_reply: str = "Simulated reply from Jarvis."
    fake_continue_listening: bool = False
    fake_response_latency: float = 0.0
    wake_delay: float = 0.0
    command_delay: float = 0.0
    followup_delay: float = 0.0
    idle_followup_delay: float = 0.0
    summary_json: bool = False


@dataclass
class SimulationResult:
    wake_triggered: bool
    wake_match: dict
    commands: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    audio_events: list[dict] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    total_seconds: float = 0.0


class Timeline:
    def __init__(self):
        self.started_at = time.perf_counter()
        self.events: dict[str, float] = {}

    def mark(self, name: str):
        self.events[name] = time.perf_counter() - self.started_at

    def elapsed(self) -> float:
        return time.perf_counter() - self.started_at


def normalize_scripted_command(text: str) -> str:
    command = clean_command_transcript(text)
    return "" if command == WAKE_ONLY_COMMAND else command


def command_from_wake_utterance(text: str) -> str:
    """Return trailing command text when a scripted wake phrase includes one."""
    return normalize_scripted_command(text)


def wav_duration_seconds(path: str) -> float:
    with wave.open(path, "rb") as audio:
        frames = audio.getnframes()
        framerate = audio.getframerate()
        return frames / framerate if framerate else 0.0


def simulation_audio_path(kind: str, index: int, suffix: str) -> str:
    SIMULATION_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    safe_kind = "".join(ch if ch.isalnum() else "-" for ch in kind).strip("-")
    return str(SIMULATION_AUDIO_DIR / f"{safe_kind}-{index}-{suffix}.wav")


def synthesize_simulation_audio(text: str, path: str) -> tuple[str, float, float]:
    started_at = time.perf_counter()
    output_path = conversation_loop.synthesize_to_wav(text, path)
    synth_seconds = time.perf_counter() - started_at
    audio_seconds = wav_duration_seconds(output_path)
    return output_path, synth_seconds, audio_seconds


def transcribe_scripted_audio(
    raw: str,
    *,
    kind: str,
    index: int,
    model,
    result: SimulationResult,
    timeline: Timeline,
) -> str:
    input_path = simulation_audio_path(kind, index, "input")
    timeline.mark(f"{kind}_input_tts_started_{index}")
    input_path, synth_seconds, audio_seconds = synthesize_simulation_audio(
        raw,
        input_path,
    )
    timeline.mark(f"{kind}_input_tts_finished_{index}")

    stt_started_at = time.perf_counter()
    command = transcribe_audio_file(input_path, model=model)
    stt_seconds = time.perf_counter() - stt_started_at
    timeline.mark(f"{kind}_stt_finished_{index}")

    result.audio_events.append(
        {
            "phase": "input",
            "kind": kind,
            "index": index,
            "text": raw,
            "audio_path": input_path,
            "tts_seconds": synth_seconds,
            "audio_seconds": audio_seconds,
            "stt_seconds": stt_seconds,
            "command": command,
        }
    )
    voice_event(
        "scripted_audio_transcribed",
        kind=kind,
        raw=raw,
        command=command,
        input_tts_seconds=f"{synth_seconds:.2f}",
        audio_seconds=f"{audio_seconds:.2f}",
        stt_seconds=f"{stt_seconds:.2f}",
    )
    return command


def transcribe_wake_audio(
    raw: str,
    *,
    result: SimulationResult,
    timeline: Timeline,
) -> str:
    input_path = simulation_audio_path("wake", 1, "input")
    timeline.mark("wake_input_tts_started")
    input_path, synth_seconds, audio_seconds = synthesize_simulation_audio(
        raw,
        input_path,
    )
    timeline.mark("wake_input_tts_finished")

    stt_started_at = time.perf_counter()
    transcript = transcribe_audio_file(input_path, clean=False)
    stt_seconds = time.perf_counter() - stt_started_at
    timeline.mark("wake_stt_finished")

    result.audio_events.append(
        {
            "phase": "input",
            "kind": "wake",
            "index": 1,
            "text": raw,
            "audio_path": input_path,
            "tts_seconds": synth_seconds,
            "audio_seconds": audio_seconds,
            "stt_seconds": stt_seconds,
            "transcript": transcript,
        }
    )
    voice_event(
        "scripted_wake_audio_transcribed",
        raw=raw,
        transcript=transcript,
        input_tts_seconds=f"{synth_seconds:.2f}",
        audio_seconds=f"{audio_seconds:.2f}",
        stt_seconds=f"{stt_seconds:.2f}",
    )
    return transcript


def wait_for_result_without_microphone(
    callable_fn: Callable,
    model,
    *args,
    on_wait_start=None,
    on_wait_start_delay=0,
    on_still_waiting=None,
    on_still_waiting_delay=0,
    **kwargs,
):
    """Run a response call while preserving checking callbacks but avoiding mic IO."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(callable_fn, *args, **kwargs)
        started_at = time.time()
        wait_started = False
        wait_started_at = None
        still_waiting_started = False

        while True:
            try:
                return future.result(timeout=0.05)
            except concurrent.futures.TimeoutError:
                pass

            if (
                on_wait_start is not None
                and not wait_started
                and time.time() - started_at >= on_wait_start_delay
                and not future.done()
            ):
                wait_started = True
                wait_started_at = time.time()
                on_wait_start()

            if (
                on_still_waiting is not None
                and wait_started
                and not still_waiting_started
                and wait_started_at is not None
                and time.time() - wait_started_at >= on_still_waiting_delay
                and not future.done()
            ):
                still_waiting_started = True
                on_still_waiting()


@contextmanager
def patched_conversation_runtime(
    options: SimulationOptions,
    timeline: Timeline,
    commands: deque[str],
    result: SimulationResult,
) -> Iterator[None]:
    original_speak = conversation_loop.speak
    original_tone = conversation_loop.confirm_command_captured
    original_get_command = conversation_loop.get_command_with_retries
    original_get_followup = conversation_loop.get_followup_until
    original_ask_pasture = conversation_loop.ask_pasture
    original_wait = conversation_loop.wait_for_result_or_wake_word
    original_refresh = conversation_loop.maybe_refresh_context_bucket_async
    original_record = conversation_loop.record_utterance

    def simulated_speak(text: str, model=None, kind: str = "speech"):
        result.replies.append(text)
        reply_index = len(result.replies)
        timeline.mark(f"spoken_{kind}_{reply_index}")
        voice_event("spoken", kind=kind, text=text)

        path = simulation_audio_path(kind, reply_index, "output")
        timeline.mark(f"output_tts_started_{kind}_{reply_index}")
        path, synth_seconds, audio_seconds = synthesize_simulation_audio(text, path)
        timeline.mark(f"output_tts_finished_{kind}_{reply_index}")
        timeline.mark(f"muted_playback_started_{kind}_{reply_index}")
        time.sleep(audio_seconds)
        timeline.mark(f"muted_playback_finished_{kind}_{reply_index}")

        result.audio_events.append(
            {
                "phase": "output",
                "kind": kind,
                "index": reply_index,
                "text": text,
                "audio_path": path,
                "tts_seconds": synth_seconds,
                "audio_seconds": audio_seconds,
                "playback_seconds": audio_seconds,
            }
        )
        voice_event(
            "playback_muted",
            kind=kind,
            path=path,
            tts_seconds=f"{synth_seconds:.2f}",
            audio_seconds=f"{audio_seconds:.2f}",
            playback_seconds=f"{audio_seconds:.2f}",
        )
        print(
            "Jarvis (muted audio): "
            f"{text} [{audio_seconds:.2f}s audio]",
            flush=True,
        )

    def simulated_tone():
        timeline.mark(f"command_captured_tone_{len(result.commands)}")
        voice_event("command_captured_tone", simulated=True)
        print("Command captured tone (muted).", flush=True)

    def next_command(kind: str, delay: float, model=None) -> str:
        voice_event("command_listen_attempt", kind=kind, simulated=True)
        if not commands:
            if options.idle_followup_delay > 0:
                time.sleep(options.idle_followup_delay)
            return ""

        if delay > 0:
            time.sleep(delay)

        raw = commands.popleft()
        command_index = len(result.commands) + 1
        command = transcribe_scripted_audio(
            raw,
            kind=kind,
            index=command_index,
            model=model,
            result=result,
            timeline=timeline,
        )
        voice_event(
            "scripted_command_supplied",
            kind=kind,
            raw=raw,
            command=command,
        )
        if command:
            result.commands.append(command)
            timeline.mark(f"{kind}_command_{len(result.commands)}")
        return command

    def simulated_get_command(model):
        return next_command("initial", options.command_delay, model=model)

    def simulated_get_followup(model, seconds: int) -> str:
        return next_command("followup", options.followup_delay, model=model)

    def fake_ask_pasture(user_text: str) -> dict:
        timeline.mark(f"response_request_{len(result.commands)}")
        voice_event("simulated_response_request", text=user_text)
        if options.fake_response_latency > 0:
            time.sleep(options.fake_response_latency)
        parsed = {
            "reply": options.fake_reply,
            "continue_listening": options.fake_continue_listening,
        }
        timeline.mark(f"response_ready_{len(result.commands)}")
        voice_event(
            "simulated_response",
            continue_listening=parsed["continue_listening"],
            reply_chars=len(parsed["reply"]),
        )
        return parsed

    def timed_real_ask_pasture(user_text: str) -> dict:
        timeline.mark(f"response_request_{len(result.commands)}")
        parsed = original_ask_pasture(user_text)
        timeline.mark(f"response_ready_{len(result.commands)}")
        return parsed

    conversation_loop.confirm_command_captured = simulated_tone
    conversation_loop.get_command_with_retries = simulated_get_command
    conversation_loop.get_followup_until = simulated_get_followup
    conversation_loop.ask_pasture = timed_real_ask_pasture
    conversation_loop.wait_for_result_or_wake_word = wait_for_result_without_microphone
    conversation_loop.maybe_refresh_context_bucket_async = lambda: None
    conversation_loop.record_utterance = lambda text, kind="command": voice_event(
        "utterance_record_skipped",
        kind=kind,
        text=text,
        reason="simulation",
    )
    if options.fake_reply:
        conversation_loop.ask_pasture = fake_ask_pasture
    conversation_loop.speak = simulated_speak

    try:
        yield
    finally:
        conversation_loop.speak = original_speak
        conversation_loop.confirm_command_captured = original_tone
        conversation_loop.get_command_with_retries = original_get_command
        conversation_loop.get_followup_until = original_get_followup
        conversation_loop.ask_pasture = original_ask_pasture
        conversation_loop.wait_for_result_or_wake_word = original_wait
        conversation_loop.maybe_refresh_context_bucket_async = original_refresh
        conversation_loop.record_utterance = original_record


def run_simulation(options: SimulationOptions) -> SimulationResult:
    utterances = [utterance for utterance in options.utterances if utterance.strip()]
    if not utterances:
        raise ValueError("at least one scripted utterance is required")

    timeline = Timeline()
    if options.wake_delay > 0:
        time.sleep(options.wake_delay)

    wake_text = utterances[0]
    result = SimulationResult(wake_triggered=False, wake_match={})
    voice_event("wake_listen_started", simulated=True)
    print("Waiting for wake word... (scripted audio)", flush=True)
    heard_wake_text = transcribe_wake_audio(wake_text, result=result, timeline=timeline)
    wake_match = get_wake_match(heard_wake_text)
    result.wake_triggered = bool(wake_match.get("triggered"))
    result.wake_match = wake_match

    if not result.wake_triggered:
        voice_event("wake_not_heard_simulated", heard=heard_wake_text, raw=wake_text)
        print(
            "No wake match for scripted utterance: "
            f"{wake_text!r} (heard {heard_wake_text!r})",
            flush=True,
        )
        result.total_seconds = timeline.elapsed()
        result.timings = timeline.events
        return result

    timeline.mark("wake_heard")
    voice_event(
        "wake_heard_simulated",
        heard=heard_wake_text,
        raw=wake_text,
        mode=wake_match.get("mode"),
        matched=wake_match.get("matched"),
    )
    print(
        "Wake match: "
        f"heard='{wake_match.get('heard')}' "
        f"matched='{wake_match.get('matched')}'",
        flush=True,
    )

    wake_command = command_from_wake_utterance(heard_wake_text)
    command_queue = deque(utterances[1:])
    if wake_command:
        command_queue.appendleft(wake_command)

    with patched_conversation_runtime(options, timeline, command_queue, result):
        wake_context_prompt = conversation_loop.speak_wake_reply(model=None)
        command = conversation_loop.get_command_with_retries(model=None)
        if command:
            conversation_loop.process_command_loop(
                model=None,
                command=command,
                served_turn=False,
                wake_context_prompt=wake_context_prompt,
            )
        else:
            voice_event("command_listen_finished", result="no_initial_command")
            print("No command heard after wake. Returning to wake word mode.", flush=True)

    result.total_seconds = timeline.elapsed()
    result.timings = timeline.events
    return result


def print_summary(result: SimulationResult, *, as_json: bool = False):
    if as_json:
        print(
            json.dumps(
                {
                    "wake_triggered": result.wake_triggered,
                    "wake_match": result.wake_match,
                    "commands": result.commands,
                    "replies": result.replies,
                    "audio_events": result.audio_events,
                    "reply_count": len(result.replies),
                    "timings": result.timings,
                    "total_seconds": result.total_seconds,
                },
                indent=2,
            )
        )
        return

    print("\nSimulation summary")
    print(f"- Wake triggered: {result.wake_triggered}")
    if result.wake_match:
        print(f"- Wake match: {result.wake_match.get('matched')}")
    if result.commands:
        print(f"- Commands: {', '.join(result.commands)}")
    else:
        print("- Commands: none")
    print(f"- Replies spoken: {len(result.replies)}")
    if result.audio_events:
        print("- Audio events:")
        for event in result.audio_events:
            label = f"{event['phase']}:{event['kind']}#{event['index']}"
            details = []
            if "tts_seconds" in event:
                details.append(f"tts={event['tts_seconds']:.2f}s")
            if "audio_seconds" in event:
                details.append(f"audio={event['audio_seconds']:.2f}s")
            if "stt_seconds" in event:
                details.append(f"stt={event['stt_seconds']:.2f}s")
            if "playback_seconds" in event:
                details.append(f"muted_playback={event['playback_seconds']:.2f}s")
            text = event.get("command") or event.get("transcript") or event.get("text")
            print(f"  - {label}: {', '.join(details)} | {text}")
    print(f"- Total elapsed: {result.total_seconds:.2f}s")

    for name, elapsed in sorted(result.timings.items(), key=lambda item: item[1]):
        print(f"- {name}: +{elapsed:.2f}s")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Simulate a Pi Jarvis wake phrase and conversation turn without using "
            "the microphone or command-server endpoint."
        )
    )
    parser.add_argument(
        "utterances",
        nargs="*",
        help=(
            "Scripted utterances. The first must contain a wake phrase; later "
            "values are initial command/follow-ups."
        ),
    )
    parser.add_argument(
        "--suite",
        help="Path to a JSON suite file with utterances and optional settings.",
    )
    return parser


def load_suite(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as suite_file:
        suite = json.load(suite_file)

    if not isinstance(suite, dict):
        raise ValueError("suite file must contain a JSON object")

    utterances = suite.get("utterances")
    if not isinstance(utterances, list) or not all(
        isinstance(item, str) for item in utterances
    ):
        raise ValueError("suite file must include an utterances string array")

    return suite


def main() -> int:
    args = build_parser().parse_args()
    suite = load_suite(args.suite) if args.suite else {}
    utterances = suite.get("utterances", args.utterances)
    if not utterances:
        raise SystemExit("provide utterances on the command line or with --suite")

    result = run_simulation(
        SimulationOptions(
            utterances=utterances,
            fake_reply=suite.get("fake_reply", "Simulated reply from Jarvis."),
            fake_continue_listening=suite.get("fake_continue_listening", False),
            fake_response_latency=suite.get("fake_response_latency", 0.0),
            wake_delay=suite.get("wake_delay", 0.0),
            command_delay=suite.get("command_delay", 0.0),
            followup_delay=suite.get("followup_delay", 0.0),
            idle_followup_delay=suite.get("idle_followup_delay", 0.0),
            summary_json=suite.get("summary_json", False),
        )
    )
    print_summary(result, as_json=suite.get("summary_json", False))
    return 0 if result.wake_triggered else 2


if __name__ == "__main__":
    raise SystemExit(main())
