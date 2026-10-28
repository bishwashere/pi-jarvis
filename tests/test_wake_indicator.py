import json
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import conversation_loop
import detect_wake_word


@pytest.mark.parametrize("final,text,expected", [
    (False, "hey jarvis", True),
    (True, "hey jarvis", True),
    (True, "jarvi", False),
    (False, "jarvi", False),
    (True, "weather forecast", False),
])
def test_indicator_only_on_accepted_wake(monkeypatch, capsys, final, text, expected):
    recognizer = SimpleNamespace(
        AcceptWaveform=lambda data: final,
        PartialResult=lambda: json.dumps({"partial": text}),
        Result=lambda: json.dumps({"text": text}),
    )
    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(
        KaldiRecognizer=lambda *args: recognizer,
    ))
    calls = []
    monkeypatch.setattr(detect_wake_word, "set_echo_conversation_active", calls.append)
    monitor = detect_wake_word.WakeWordMonitor(None)
    assert monitor.accept_audio(b"audio") is expected
    assert calls == ([True] if expected else [])
    output = capsys.readouterr().out
    assert ("[Vosk] Heard:" if final else "[Vosk] Heard partial:") in output
    assert ("wake_heard detector='vosk'" in output) is expected
    if expected:
        # A suppressed duplicate must not relight an idle ring.
        calls.clear()
        assert monitor.accept_audio(b"audio") is False
        assert calls == []
        output = capsys.readouterr().out
        assert "wake_detection_ignored detector='vosk'" in output
        assert "reason='duplicate'" in output
        assert "wake_heard" not in output


@pytest.mark.parametrize("text", [
    "he there is", "hi", "below this", "birds are", "heyday", "shelloworld", "hey", "hey there",
])
def test_default_wake_rejects_observed_false_matches(text):
    assert detect_wake_word.get_wake_match(text)["triggered"] is False


@pytest.mark.parametrize("text", ["hey jarvis", "hello", "hey computer", "hello there"])
def test_standalone_greetings_are_wake_phrases(text):
    assert detect_wake_word.get_wake_match(text)["triggered"] is True


def test_fuzzy_matching_requires_opt_in_and_complete_result(monkeypatch):
    monkeypatch.setattr(detect_wake_word, "LENIENT_WAKE_LEVEL", 20)
    assert detect_wake_word.get_wake_match("jarvi")["triggered"] is True
    assert detect_wake_word.get_wake_match("jarvi", allow_lenient=False)["triggered"] is False


def test_partial_then_final_does_not_trigger_twice(monkeypatch):
    final = iter([False, True])
    recognizer = SimpleNamespace(
        AcceptWaveform=lambda data: next(final),
        PartialResult=lambda: '{"partial":"hey jarvis"}',
        Result=lambda: '{"text":"hey jarvis"}',
    )
    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(
        KaldiRecognizer=lambda *args: recognizer,
    ))
    calls = []
    monkeypatch.setattr(detect_wake_word, "set_echo_conversation_active", calls.append)
    monitor = detect_wake_word.WakeWordMonitor(None)
    assert monitor.accept_audio(b"audio") is True
    assert monitor.accept_audio(b"audio") is False
    assert calls == [True]


def test_acoustic_wake_works_even_when_transcript_is_wrong(monkeypatch, capsys):
    recognizer = SimpleNamespace(
        AcceptWaveform=lambda data: True,
        Result=lambda: '{"text":"it is obvious"}',
    )
    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(
        KaldiRecognizer=lambda *args: recognizer,
    ))
    scores = iter([0.82, None])
    monkeypatch.setattr(detect_wake_word, "consume_echo_wake", lambda: next(scores))
    calls = []
    monkeypatch.setattr(detect_wake_word, "set_echo_conversation_active", calls.append)
    monitor = detect_wake_word.WakeWordMonitor(None)
    assert monitor.accept_audio(b"audio") is True
    output = capsys.readouterr().out
    assert "wake_heard detector='openwakeword'" in output
    assert "score='0.82'" in output
    assert monitor.last_command_after_wake == ""
    assert monitor.accept_audio(b"audio") is False
    assert calls == [True]


@pytest.mark.parametrize("failure", [None, RuntimeError("conversation failed")])
def test_ring_clears_on_return_to_idle_and_on_failure(monkeypatch, failure):
    calls = []
    monkeypatch.setattr(conversation_loop, "set_echo_conversation_active", calls.append)
    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(Model=lambda path: None))
    monitor = SimpleNamespace(
        accept_audio=lambda data: calls.append(True) or True,
        reset=lambda: None,
        last_command_after_wake="",
    )
    monkeypatch.setattr(conversation_loop, "WakeWordMonitor", lambda model: monitor)
    monkeypatch.setattr(conversation_loop, "check_agent_health", lambda: None)
    monkeypatch.setattr(conversation_loop, "play_online_tone", lambda: None)
    monkeypatch.setattr(conversation_loop, "COMMAND_SERVER_ENABLED", False)
    pending = iter([None, None])  # enter wake wait, then accept one audio frame
    monkeypatch.setattr(conversation_loop, "get_pending_local_command", lambda: next(pending))
    monkeypatch.setattr(conversation_loop, "stand_down_remaining", lambda: 0)
    monkeypatch.setattr(conversation_loop, "open_microphone_stream", nullcontext)
    monkeypatch.setattr(conversation_loop, "clear_audio_queue", lambda: None)
    monkeypatch.setattr(conversation_loop, "audio_queue", SimpleNamespace(get=lambda **kw: b"audio"))

    def conversation(model):
        assert calls[-1] is True
        if failure:
            raise failure

    monkeypatch.setattr(conversation_loop, "handle_conversation", conversation)
    with pytest.raises(RuntimeError if failure else StopIteration):
        conversation_loop.run_assistant()
    assert calls == ([False, True, False] if failure else [False, True, False, False])
