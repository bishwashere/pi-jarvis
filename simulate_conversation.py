"""Scripted end-to-end conversation simulation for Pi Jarvis.

This exercises the normal wake -> command -> API -> reply conversation path
without opening the microphone. By default it also mutes TTS/playback and uses a
fake API reply, so it is safe to run on development machines and in tests.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator

import conversation_loop
from detect_wake_word import get_wake_match
from speech_to_text import WAKE_ONLY_COMMAND, clean_command_transcript
from voice_log import voice_event


@dataclass
class SimulationOptions:
    utterances: list[str]
    real_api: bool = False
    fake_reply: str = "Simulated reply from Jarvis."
    fake_continue_listening: bool = False
    fake_api_latency: float = 0.0
    wake_delay: float = 0.0
    command_delay: float = 0.0
    followup_delay: float = 0.0
    idle_followup_delay: float = 0.0
    audio_mode: str = "muted"
    speak_audio: bool = False
    summary_json: bool = False


@dataclass
class SimulationResult:
    wake_triggered: bool
    wake_match: dict
    commands: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
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
    """Run an API call while preserving checking callbacks but avoiding mic IO."""
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
    original_ask = conversation_loop.ask_pasture
    original_wait = conversation_loop.wait_for_result_or_wake_word
    original_refresh = conversation_loop.maybe_refresh_context_bucket_async
    original_record = conversation_loop.record_utterance

    def simulated_speak(text: str, model=None, kind: str = "speech"):
        result.replies.append(text)
        reply_index = len(result.replies)
        timeline.mark(f"spoken_{kind}_{reply_index}")
        voice_event("spoken", kind=kind, text=text)

        if options.audio_mode == "synthesize":
            timeline.mark(f"tts_started_{kind}_{reply_index}")
            path = conversation_loop.synthesize_to_wav(text)
            timeline.mark(f"tts_finished_{kind}_{reply_index}")
            voice_event(
                "playback_skipped",
                kind=kind,
                path=path,
                reason="simulation_audio_mode_synthesize",
            )
            print(f"Playback skipped for synthesized audio: {path}", flush=True)
            return

        print(f"Jarvis (muted): {text}", flush=True)

    def simulated_tone():
        timeline.mark(f"command_captured_tone_{len(result.commands)}")
        voice_event("command_captured_tone", simulated=True)
        print("Command captured tone (muted).", flush=True)

    def next_command(kind: str, delay: float) -> str:
        voice_event("command_listen_attempt", kind=kind, simulated=True)
        if not commands:
            if options.idle_followup_delay > 0:
                time.sleep(options.idle_followup_delay)
            return ""

        if delay > 0:
            time.sleep(delay)

        raw = commands.popleft()
        command = normalize_scripted_command(raw)
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
        return next_command("initial", options.command_delay)

    def simulated_get_followup(model, seconds: int) -> str:
        return next_command("followup", options.followup_delay)

    def fake_ask_pasture(user_text: str) -> dict:
        timeline.mark(f"api_request_{len(result.commands)}")
        voice_event("simulated_api_request", text=user_text)
        if options.fake_api_latency > 0:
            time.sleep(options.fake_api_latency)
        parsed = {
            "reply": options.fake_reply,
            "continue_listening": options.fake_continue_listening,
        }
        timeline.mark(f"api_response_{len(result.commands)}")
        voice_event(
            "simulated_api_response",
            continue_listening=parsed["continue_listening"],
            reply_chars=len(parsed["reply"]),
        )
        return parsed

    def timed_real_ask_pasture(user_text: str) -> dict:
        timeline.mark(f"api_request_{len(result.commands)}")
        parsed = original_ask(user_text)
        timeline.mark(f"api_response_{len(result.commands)}")
        return parsed

    conversation_loop.confirm_command_captured = simulated_tone
    conversation_loop.get_command_with_retries = simulated_get_command
    conversation_loop.get_followup_until = simulated_get_followup
    conversation_loop.ask_pasture = timed_real_ask_pasture if options.real_api else fake_ask_pasture
    conversation_loop.wait_for_result_or_wake_word = wait_for_result_without_microphone
    if not options.real_api:
        conversation_loop.maybe_refresh_context_bucket_async = lambda: None
        conversation_loop.record_utterance = lambda text, kind="command": voice_event(
            "utterance_record_skipped",
            kind=kind,
            text=text,
            reason="fake_api_simulation",
        )
    if options.audio_mode not in {"muted", "synthesize", "play"}:
        raise ValueError("audio_mode must be 'muted', 'synthesize', or 'play'")

    if options.speak_audio:
        options.audio_mode = "play"

    if options.audio_mode != "play":
        conversation_loop.speak = simulated_speak

    try:
        yield
    finally:
        conversation_loop.speak = original_speak
        conversation_loop.confirm_command_captured = original_tone
        conversation_loop.get_command_with_retries = original_get_command
        conversation_loop.get_followup_until = original_get_followup
        conversation_loop.ask_pasture = original_ask
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
    voice_event("wake_listen_started", simulated=True)
    print("Waiting for wake word... (scripted)", flush=True)
    wake_match = get_wake_match(wake_text)
    result = SimulationResult(
        wake_triggered=bool(wake_match.get("triggered")),
        wake_match=wake_match,
    )

    if not result.wake_triggered:
        voice_event("wake_not_heard_simulated", heard=wake_text)
        print(f"No wake match for scripted utterance: {wake_text!r}", flush=True)
        result.total_seconds = timeline.elapsed()
        result.timings = timeline.events
        return result

    timeline.mark("wake_heard")
    voice_event(
        "wake_heard_simulated",
        heard=wake_text,
        mode=wake_match.get("mode"),
        matched=wake_match.get("matched"),
    )
    print(
        "Wake match: "
        f"heard='{wake_match.get('heard')}' "
        f"matched='{wake_match.get('matched')}'",
        flush=True,
    )

    wake_command = command_from_wake_utterance(wake_text)
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
    parser.add_argument("--real-api", action="store_true", help="Call the configured Jarvis API.")
    parser.add_argument("--fake-reply")
    parser.add_argument("--fake-continue-listening", action="store_true")
    parser.add_argument("--fake-api-latency", type=float)
    parser.add_argument("--wake-delay", type=float)
    parser.add_argument("--command-delay", type=float)
    parser.add_argument("--followup-delay", type=float)
    parser.add_argument("--idle-followup-delay", type=float)
    parser.add_argument(
        "--speak-audio",
        action="store_true",
        help="Use real Piper/playback instead of muted spoken output.",
    )
    parser.add_argument(
        "--audio-mode",
        choices=["muted", "synthesize", "play"],
        help=(
            "muted logs speech only; synthesize runs TTS but skips playback; "
            "play uses the real speaker path."
        ),
    )
    parser.add_argument("--summary-json", action="store_true")
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


def value_from_args_or_suite(args, suite: dict, name: str, default):
    value = getattr(args, name)
    if value not in {None, False}:
        return value
    if name in suite:
        return suite[name]
    return default


def main() -> int:
    args = build_parser().parse_args()
    suite = load_suite(args.suite) if args.suite else {}
    utterances = suite.get("utterances", args.utterances)
    if not utterances:
        raise SystemExit("provide utterances on the command line or with --suite")

    result = run_simulation(
        SimulationOptions(
            utterances=utterances,
            real_api=value_from_args_or_suite(args, suite, "real_api", False),
            fake_reply=value_from_args_or_suite(
                args,
                suite,
                "fake_reply",
                "Simulated reply from Jarvis.",
            ),
            fake_continue_listening=value_from_args_or_suite(
                args,
                suite,
                "fake_continue_listening",
                False,
            ),
            fake_api_latency=value_from_args_or_suite(
                args,
                suite,
                "fake_api_latency",
                0.0,
            ),
            wake_delay=value_from_args_or_suite(args, suite, "wake_delay", 0.0),
            command_delay=value_from_args_or_suite(args, suite, "command_delay", 0.0),
            followup_delay=value_from_args_or_suite(args, suite, "followup_delay", 0.0),
            idle_followup_delay=value_from_args_or_suite(
                args,
                suite,
                "idle_followup_delay",
                0.0,
            ),
            audio_mode=value_from_args_or_suite(args, suite, "audio_mode", "muted"),
            speak_audio=value_from_args_or_suite(args, suite, "speak_audio", False),
            summary_json=value_from_args_or_suite(args, suite, "summary_json", False),
        )
    )
    print_summary(
        result,
        as_json=value_from_args_or_suite(args, suite, "summary_json", False),
    )
    return 0 if result.wake_triggered else 2


if __name__ == "__main__":
    raise SystemExit(main())
