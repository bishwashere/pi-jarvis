import json
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import speech_to_text
import conversation_loop


@pytest.mark.parametrize("enabled", [False, True])
def test_waiting_announcements_setting_keeps_answer(monkeypatch, enabled):
    callbacks = {}
    spoken = []
    def wait(func, model, text, **kwargs):
        callbacks.update(kwargs)
        return {"reply": "4", "continue_listening": False}
    monkeypatch.setattr(conversation_loop, "WAITING_ANNOUNCEMENTS", enabled)
    monkeypatch.setattr(conversation_loop, "wait_for_result_or_wake_word", wait)
    monkeypatch.setattr(conversation_loop, "speak",
                        lambda text, **kwargs: spoken.append(text))
    assert conversation_loop.ask_and_speak("two plus two", None) is False
    assert bool(callbacks["on_wait_start"]) is enabled
    assert bool(callbacks["on_still_waiting"]) is enabled
    assert spoken == ["4"]


@pytest.mark.parametrize("transcript,expected", [
    ("What is 2+2?", "what is 2 plus 2"),
    ("Jarvis, what is 8 + 2?", "what is 8 plus 2"),
    ("What is 2+3+4?", "what is 2 plus 3 plus 4"),
    ("Set the date to 10/20/2026", "set the date to 10 20 2026"),
    ("What is two plus two?", "what is two plus two"),
])
def test_command_cleanup_retains_numeric_operators(transcript, expected):
    assert speech_to_text.clean_command_transcript(transcript) == expected


def test_vosk_streams_without_recording_a_whisper_clip(monkeypatch, capsys):
    clock = SimpleNamespace(now=0.0)
    chunks = []

    def get_audio(timeout):
        clock.now += 0.3
        return b"audio chunk"

    def accept(data):
        chunks.append(data)
        return len(chunks) == 1

    recognizer = SimpleNamespace(
        AcceptWaveform=accept,
        Result=lambda: '{"text":"what is two plus two"}',
        PartialResult=lambda: '{"partial":""}',
        FinalResult=lambda: '{"text":""}',
    )
    monkeypatch.setitem(sys.modules, "vosk", SimpleNamespace(
        KaldiRecognizer=lambda *args: recognizer,
    ))
    monkeypatch.setattr(speech_to_text, "COMMAND_STT_ENGINE", "vosk")
    monkeypatch.setattr(speech_to_text, "time", SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setattr(speech_to_text, "clear_audio_queue", lambda: None)
    monkeypatch.setattr(speech_to_text, "open_microphone_stream", nullcontext)
    monkeypatch.setattr(speech_to_text, "audio_queue", SimpleNamespace(get=get_audio))
    monkeypatch.setattr(speech_to_text, "record_command_audio",
                        lambda *a, **kw: pytest.fail("Streaming Vosk must not record a clip"))
    assert speech_to_text.listen_for_command(object(), seconds=60) == "what is two plus two"
    assert len(chunks) == 4
    output = capsys.readouterr().out
    assert "command_listen_started engine='vosk'" in output
    assert "vosk_transcript" in output


@pytest.mark.parametrize("final,expected", [(False, ""), (True, "nothing")])
def test_quick_candidate_requires_final_result(final, expected):
    recognizer = SimpleNamespace(
        AcceptWaveform=lambda data: final,
        Result=lambda: json.dumps({"text": "nothing"}),
        PartialResult=lambda: pytest.fail("Partial guesses must not become commands"),
    )
    assert speech_to_text.detect_quick_command(recognizer, b"audio", "test") == expected


def test_quick_candidate_does_not_cut_off_recording(monkeypatch, tmp_path):
    clock = SimpleNamespace(now=0.0)
    # A false "nothing" guess during ongoing speech, followed by more speech
    # and then two seconds of silence. Every frame must reach the saved WAV.
    frames = [b"\xe8\x03" * 160] * 4 + [b"\x00\x00" * 160] * 4
    remaining = iter(frames)

    def get_audio(timeout):
        clock.now += 0.5
        return next(remaining)

    written = []
    monkeypatch.setattr(speech_to_text, "time", SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setattr(speech_to_text, "clear_audio_queue", lambda: None)
    monkeypatch.setattr(speech_to_text, "open_microphone_stream", nullcontext)
    monkeypatch.setattr(speech_to_text, "audio_queue", SimpleNamespace(get=get_audio))
    monkeypatch.setattr(speech_to_text, "build_quick_command_recognizer", lambda model: object())
    monkeypatch.setattr(
        speech_to_text, "detect_quick_command",
        lambda *args, **kwargs: "nothing" if clock.now == 1 else "",
    )
    monkeypatch.setattr(speech_to_text, "COMMAND_SILENCE_SECONDS", 2.0)
    monkeypatch.setattr(speech_to_text, "COMMAND_AUDIO_RMS_THRESHOLD", 420)
    monkeypatch.setattr(speech_to_text, "COMMAND_MIN_RECORD_SECONDS", 0.7)
    path = str(tmp_path / "command.wav")
    monkeypatch.setattr(speech_to_text, "COMMAND_RECORDING_PATH", path)
    monkeypatch.setattr(speech_to_text, "write_wav", lambda path, audio: written.extend(audio))

    assert speech_to_text.record_command_audio(60, model=object()) == ("nothing", path)
    assert clock.now == 4
    assert written == frames


@pytest.mark.parametrize("transcript", ["nothing", "nothing happens when i ask the time", ""])
def test_whisper_decides_command_even_after_quick_candidate(monkeypatch, capsys, transcript):
    monkeypatch.setattr(speech_to_text, "time", SimpleNamespace(time=lambda: 0))
    recordings = iter([("nothing", "recorded.wav"), ("", "")])
    monkeypatch.setattr(speech_to_text, "record_command_audio", lambda *a, **kw: next(recordings))
    transcribed = []

    def transcribe(path):
        transcribed.append(path)
        return transcript

    monkeypatch.setattr(speech_to_text, "transcribe_with_whisper", transcribe)
    assert speech_to_text.listen_for_command_with_whisper(object(), 60) == transcript
    assert transcribed == ["recorded.wav"]
    output = capsys.readouterr().out
    assert f"confirmed='{transcript == 'nothing'}'" in output


@pytest.mark.parametrize('silence_seconds', [1.5, 2.0])
def test_capture_keeps_speech_after_one_second_pause(monkeypatch, silence_seconds):
    clock = SimpleNamespace(now=0.0)
    speech = b'\xe8\x03' * 160
    quiet = b'\x00\x00' * 160
    frames = [speech] * 4 + [quiet] * 4 + [speech] * 4 + [quiet] * 8
    remaining = iter(frames)
    def get_audio(timeout):
        clock.now += 0.25
        return next(remaining)
    written = []
    monkeypatch.setattr(speech_to_text, 'time', SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setattr(speech_to_text, 'clear_audio_queue', lambda: None)
    monkeypatch.setattr(speech_to_text, 'open_microphone_stream', nullcontext)
    monkeypatch.setattr(speech_to_text, 'audio_queue', SimpleNamespace(get=get_audio))
    monkeypatch.setattr(speech_to_text, 'build_quick_command_recognizer', lambda model: None)
    monkeypatch.setattr(speech_to_text, 'COMMAND_SILENCE_SECONDS', silence_seconds)
    monkeypatch.setattr(speech_to_text, 'COMMAND_AUDIO_RMS_THRESHOLD', 420)
    monkeypatch.setattr(speech_to_text, 'write_wav', lambda path, audio: written.extend(audio))
    speech_to_text.record_command_audio(60)
    assert written.count(speech) == 8
    assert clock.now == 3.0 + silence_seconds
