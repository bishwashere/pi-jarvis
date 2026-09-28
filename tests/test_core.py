import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import call_agent_api
import conversation_loop
import listen_to_mic
import play_audio
import speech_to_text
import text_to_speech
import simulate_conversation
from daily_context import contextualize_affirmative_command, parse_suggestions
from detect_wake_word import get_wake_match, remove_phrase
from call_agent_api import parse_agent_reply
from speech_to_text import (
    QUICK_COMMANDS,
    WAKE_ONLY_COMMAND,
    calculate_rms,
    clean_command_transcript,
    remove_wake_words,
    write_wav,
)
from text_to_speech import clean_for_tts


def test_parse_agent_reply_supports_plain_text_and_json():
    assert parse_agent_reply("A plain answer") == {
        "reply": "A plain answer",
        "continue_listening": False,
    }
    assert parse_agent_reply(
        '{"reply":"Need more detail","continue_listening":true}'
    ) == {
        "reply": "Need more detail",
        "continue_listening": True,
    }


def test_wake_word_and_text_cleanup():
    assert get_wake_match("hey jarvis")["triggered"] is True
    assert get_wake_match("below this") == {
        "triggered": True,
        "mode": "alias",
        "heard": "below this",
        "matched": "hello",
        "candidate": "below",
        "score": 1.0,
    }
    assert remove_wake_words("hey jarvis tell me the time") == "tell me the time"
    assert remove_phrase("jarvis stand down", "jarvis") == "stand down"
    assert remove_phrase("hello jarvis stand down", "hello jarvis") == "stand down"
    assert clean_command_transcript("Hi.") == WAKE_ONLY_COMMAND
    assert clean_command_transcript("hello computer?") == WAKE_ONLY_COMMAND
    assert clean_command_transcript("Jarvis, what time is it?") == "what time is it"
    assert "yes" in QUICK_COMMANDS
    assert "do nothing" in QUICK_COMMANDS
    assert "weather today" not in QUICK_COMMANDS
    assert "what time is it" not in QUICK_COMMANDS
    assert clean_for_tts("[Jarvis] **Hello**   there") == "Hello there"
    assert calculate_rms(b"\x00\x00" * 20) == 0


def test_scripted_conversation_simulates_wake_to_reply(capsys, monkeypatch):
    transcripts = iter(["hey jarvis", "what time is it"])

    def fake_synthesize(text, output_path):
        frames = b"\x00\x00" * 160
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(output_path, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(frames)
        return output_path

    monkeypatch.setattr(conversation_loop, "synthesize_to_wav", fake_synthesize)
    monkeypatch.setattr(
        simulate_conversation,
        "transcribe_audio_file",
        lambda path, model=None, clean=True: next(transcripts),
    )

    result = simulate_conversation.run_simulation(
        simulate_conversation.SimulationOptions(
            utterances=["hey jarvis", "what time is it"],
            fake_reply="It is test time.",
        )
    )

    output = capsys.readouterr().out

    assert result.wake_triggered is True
    assert result.commands == ["what time is it"]
    assert "Voice event: wake_heard_simulated" in output
    assert "Command: what time is it" in output
    assert "Jarvis (muted audio): It is test time." in output


def test_audio_simulation_transcribes_input_and_waits_for_muted_output(monkeypatch):
    transcripts = iter(["hey jarvis", "what time is it"])

    def fake_synthesize(text, output_path):
        frames = b"\x00\x00" * 160
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with wave.open(output_path, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(frames)
        return output_path

    monkeypatch.setattr(conversation_loop, "synthesize_to_wav", fake_synthesize)
    monkeypatch.setattr(
        simulate_conversation,
        "transcribe_audio_file",
        lambda path, model=None, clean=True: next(transcripts),
    )

    result = simulate_conversation.run_simulation(
        simulate_conversation.SimulationOptions(
            utterances=["hey jarvis", "what time is it"],
            fake_reply="It is test time.",
        )
    )

    assert result.commands == ["what time is it"]
    assert any(
        event["phase"] == "input"
        and event["kind"] == "initial"
        and event["stt_seconds"] >= 0
        for event in result.audio_events
    )
    assert any(
        event["phase"] == "output"
        and event["kind"] == "answer"
        and event["audio_seconds"] == 0.01
        and event["playback_seconds"] == 0.01
        for event in result.audio_events
    )


def test_daily_context_suggestions_and_affirmative_bridge():
    assert parse_suggestions(
        '{"suggestions":["Do you still want to check the weather?", "Open the camera?"]}'
    ) == ["Do you still want to check the weather?", "Open the camera?"]
    assert contextualize_affirmative_command(
        "yes",
        "Do you still want to check the weather?",
    ) == "Yes. The wake prompt was: Do you still want to check the weather?"
    assert contextualize_affirmative_command("what time is it", "Check weather?") == "what time is it"


def test_write_wav_accepts_a_filename_without_a_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_wav("command.wav", [b"\x00\x00" * 40])

    with wave.open("command.wav", "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 16000
        assert audio.getnframes() == 40


def test_quick_command_is_ignored_before_speech_threshold(monkeypatch):
    class FakeAudioQueue:
        def __init__(self):
            self.returned_frame = False

        def get(self, timeout):
            if not self.returned_frame:
                self.returned_frame = True
                return b"\x01\x00" * 160
            raise speech_to_text.queue.Empty

    class NoopStream:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, traceback):
            return False

    quick_calls = []
    monkeypatch.setattr(speech_to_text, "clear_audio_queue", lambda: None)
    monkeypatch.setattr(speech_to_text, "open_microphone_stream", lambda: NoopStream())
    monkeypatch.setattr(speech_to_text, "audio_queue", FakeAudioQueue())
    monkeypatch.setattr(speech_to_text, "build_quick_command_recognizer", lambda model: object())
    monkeypatch.setattr(
        speech_to_text,
        "detect_quick_command",
        lambda recognizer, data, source: quick_calls.append(data) or "bye",
    )
    monkeypatch.setattr(speech_to_text, "voice_event", lambda *args, **kwargs: None)

    assert speech_to_text.record_command_audio(0.01, model=object()) == ("", "")
    assert quick_calls == []


def test_ask_and_speak_uses_pasture_protocol(monkeypatch):
    monkeypatch.setattr(conversation_loop, "voice_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(conversation_loop, "speak", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        conversation_loop,
        "wait_for_result_or_wake_word",
        lambda func, model, user_text, **kwargs: func(user_text),
    )
    captured = {}

    def fake_ask_pasture(user_text):
        captured["user_text"] = user_text
        return {"reply": "From Passer.", "continue_listening": False}

    monkeypatch.setattr(conversation_loop, "ask_pasture", fake_ask_pasture)

    assert conversation_loop.ask_and_speak("thank you", object()) is False
    assert captured == {"user_text": "thank you"}


def test_ask_and_speak_can_suppress_waiting_announcements(monkeypatch):
    wait_kwargs = {}

    monkeypatch.setattr(conversation_loop, "voice_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(conversation_loop, "speak", lambda *args, **kwargs: None)

    def fake_wait(func, model, user_text, **kwargs):
        wait_kwargs.update(kwargs)
        return {"reply": "You are welcome.", "continue_listening": False}

    monkeypatch.setattr(conversation_loop, "wait_for_result_or_wake_word", fake_wait)

    assert (
        conversation_loop.ask_and_speak(
            "thank you",
            object(),
            announce_waiting=False,
        )
        is False
    )
    assert wait_kwargs["on_wait_start"] is None
    assert wait_kwargs["on_still_waiting"] is None


def test_stand_down_command_starts_one_hour_quiet_mode(monkeypatch):
    spoken = []
    events = []

    monkeypatch.setattr(conversation_loop.time, "time", lambda: 1000.0)
    monkeypatch.setattr(conversation_loop.time, "localtime", lambda timestamp=None: object())
    monkeypatch.setattr(
        conversation_loop.time,
        "strftime",
        lambda fmt, value: "2026-09-28T14:00:00",
    )
    monkeypatch.setattr(conversation_loop, "_stand_down_until", 0.0)
    monkeypatch.setattr(conversation_loop, "STAND_DOWN_SECONDS", 3600)
    monkeypatch.setattr(conversation_loop, "voice_event", lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(conversation_loop, "confirm_command_captured", lambda: None)
    monkeypatch.setattr(
        conversation_loop,
        "speak",
        lambda text, model=None, kind="speech": spoken.append((text, kind)),
    )
    monkeypatch.setattr(
        conversation_loop,
        "ask_and_speak",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stand down should not call Passer")
        ),
    )

    assert conversation_loop.is_stand_down_command("jarvis stand down") is True
    assert conversation_loop.is_stand_down_command("stand down") is True

    conversation_loop.process_command_loop(object(), "stand down")

    assert conversation_loop.stand_down_remaining(now=1000.0) == 3600.0
    assert conversation_loop.is_standing_down(now=4599.0) is True
    assert conversation_loop.is_standing_down(now=4600.0) is False
    assert spoken == [("Standing down for one hour.", "stand_down")]
    assert any(args == ("stand_down_started",) for args, kwargs in events)


def test_tts_creates_parent_and_invokes_configured_piper(tmp_path, monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        return subprocess.CompletedProcess(args, 0)

    output_path = tmp_path / "nested/reply.wav"
    monkeypatch.setattr(text_to_speech, "resolve_piper_binary", lambda: "/venv/piper")
    monkeypatch.setattr(text_to_speech.subprocess, "run", fake_run)

    returned = text_to_speech.synthesize_to_wav("**Ready**", str(output_path))

    assert returned == str(output_path)
    assert output_path.parent.is_dir()
    assert captured["args"][0] == "/venv/piper"
    assert captured["args"][1:3] == ["--model", text_to_speech.PIPER_MODEL_PATH]
    assert captured["kwargs"]["input"] == "Ready"
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["check"] is True


def test_volume_configuration_can_be_disabled(monkeypatch):
    def unexpected_run(*args, **kwargs):
        raise AssertionError("amixer should not run")

    monkeypatch.setattr(play_audio, "CONFIGURE_VOLUME", False)
    monkeypatch.setattr(play_audio.subprocess, "run", unexpected_run)
    play_audio.ensure_speaker_volume()


def test_command_server_chime_uses_short_rising_tone(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        play_audio,
        "write_tone",
        lambda path, notes, volume=0.35: captured.update(
            path=path,
            notes=notes,
            volume=volume,
        ),
    )
    monkeypatch.setattr(play_audio, "play_wav_file", lambda path: captured.update(played=path))

    play_audio.play_command_server_chime()

    assert captured["path"] == play_audio.COMMAND_SERVER_CHIME_PATH
    assert captured["played"] == play_audio.COMMAND_SERVER_CHIME_PATH
    assert captured["volume"] == 0.18
    assert captured["notes"][-1] == (2093.0, 0.24)


def test_alsa_playback_stringifies_numeric_device(monkeypatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        def communicate(self):
            return "", ""

    def fake_popen(args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        return FakeProcess()

    monkeypatch.setattr(play_audio, "PLAYBACK_DEVICE", 7)
    monkeypatch.setattr(play_audio, "ensure_speaker_volume", lambda: None)
    monkeypatch.setattr(play_audio.subprocess, "Popen", fake_popen)

    play_audio.play_wav_with_alsa("reply.wav")

    assert captured["args"][1:3] == ["-D", "7"]


def test_automatic_playback_backend_preserves_linux_and_supports_windows(monkeypatch):
    monkeypatch.setattr(play_audio, "PLAYBACK_BACKEND", "auto")
    monkeypatch.setattr(play_audio, "sys", SimpleNamespace(platform="linux"))
    assert play_audio.resolve_playback_backend() == "alsa"

    monkeypatch.setattr(play_audio, "sys", SimpleNamespace(platform="win32"))
    assert play_audio.resolve_playback_backend() == "sounddevice"

    monkeypatch.setattr(play_audio, "PLAYBACK_BACKEND", "alsa")
    assert play_audio.resolve_playback_backend() == "alsa"


def test_sounddevice_playback_streams_pcm_wav_without_alsa(tmp_path, monkeypatch):
    wav_path = tmp_path / "reply.wav"
    frames = b"\x01\x00\x02\x00" * 32
    with wave.open(str(wav_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(22050)
        audio.writeframes(frames)

    captured = {"writes": []}

    class FakeOutputStream:
        def __init__(self, **kwargs):
            captured["options"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def write(self, data):
            captured["writes"].append(data)
            return False

    monkeypatch.setattr(play_audio, "PLAYBACK_DEVICE", "default")
    monkeypatch.setattr(play_audio.sd, "RawOutputStream", FakeOutputStream)

    play_audio.play_wav_with_sounddevice(str(wav_path))

    assert captured["options"] == {
        "samplerate": 22050,
        "channels": 1,
        "dtype": "int16",
        "device": None,
    }
    assert b"".join(captured["writes"]) == frames


def test_playback_dispatches_to_sounddevice(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        play_audio,
        "resolve_playback_backend",
        lambda: "sounddevice",
    )
    monkeypatch.setattr(
        play_audio,
        "play_wav_with_sounddevice",
        lambda path, model=None: captured.update(path=path, model=model),
    )
    monkeypatch.setattr(
        play_audio,
        "play_wav_with_alsa",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ALSA must not run")
        ),
    )

    model = object()
    play_audio.play_wav_file("reply.wav", model=model)

    assert captured == {"path": "reply.wav", "model": model}


def test_default_microphone_maps_to_portaudio_default(monkeypatch):
    captured = {}

    def fake_check_input_settings(**kwargs):
        captured["checked_device"] = kwargs["device"]

    def fake_query_devices(device, kind):
        captured["queried_device"] = device
        assert kind == "input"
        return {"name": "Windows default microphone", "max_input_channels": 1}

    monkeypatch.setattr(
        listen_to_mic.sd,
        "check_input_settings",
        fake_check_input_settings,
    )
    monkeypatch.setattr(listen_to_mic.sd, "query_devices", fake_query_devices)

    result = listen_to_mic.query_input_device("default")

    assert result["name"] == "Windows default microphone"
    assert captured == {"checked_device": None, "queried_device": None}


def test_piper_resolver_finds_windows_venv_executable(tmp_path, monkeypatch):
    scripts_dir = tmp_path / "Scripts"
    scripts_dir.mkdir()
    python_path = scripts_dir / "python.exe"
    piper_path = scripts_dir / "piper.exe"
    python_path.touch()
    piper_path.touch()

    monkeypatch.setattr(text_to_speech, "PIPER_BINARY", "piper")
    monkeypatch.setattr(text_to_speech.shutil, "which", lambda executable: None)
    monkeypatch.setattr(text_to_speech.sys, "executable", str(python_path))

    assert text_to_speech.resolve_piper_binary() == str(piper_path)


def test_windows_launcher_uses_native_venv_and_portable_audio():
    launcher = Path(__file__).resolve().parents[1] / "run_local.ps1"
    contents = launcher.read_text(encoding="utf-8")

    assert "$PSScriptRoot" in contents
    assert "Scripts\\python.exe" in contents
    assert '"JARVIS_COMMAND_STT_ENGINE" "vosk"' in contents
    assert '"JARVIS_PLAYBACK_BACKEND" "sounddevice"' in contents
    assert "$env:JARVIS_PROJECT_DIR = $ProjectDir" in contents
    assert "Set-JarvisDefault" in contents
    assert '& $PythonPath (Join-Path $ProjectDir "jarvis_voice.py")' in contents
    assert "exit $ExitCode" in contents
    assert "flock" not in contents
    assert "aplay" not in contents
    assert "Activate.ps1" not in contents
    assert "bin/python" not in contents
    assert "/tmp" not in contents


def test_conversation_happy_path_without_hardware(monkeypatch):
    calls = []
    monkeypatch.setattr(conversation_loop, "speak", lambda text, **kwargs: None)
    monkeypatch.setattr(
        conversation_loop,
        "get_command_with_retries",
        lambda model: "what time is it",
    )
    monkeypatch.setattr(
        conversation_loop,
        "ask_and_speak",
        lambda text, model, **kwargs: calls.append(text) or False,
    )
    monkeypatch.setattr(
        conversation_loop,
        "listen_for_command",
        lambda model, seconds: "",
    )

    conversation_loop.handle_conversation(object())

    assert calls == ["what time is it"]


def test_local_command_is_queued_for_voice_loop():
    while conversation_loop.get_pending_local_command():
        pass

    result = conversation_loop.handle_local_command({"instruction": "Welcome home."})

    assert result == {"ok": True, "queued": True, "text": "Welcome home."}
    assert conversation_loop.get_pending_local_command() == {"text": "Welcome home."}


def test_command_server_instruction_acts_as_wake_and_listens_for_command(monkeypatch):
    events = []

    monkeypatch.setattr(conversation_loop, "clear_audio_queue", lambda: events.append(("clear",)))
    monkeypatch.setattr(
        conversation_loop,
        "speak",
        lambda text, model=None, kind="speech": events.append(("speak", text, kind)),
    )
    monkeypatch.setattr(
        conversation_loop,
        "play_command_server_preamble",
        lambda: events.append(("chime",)),
    )
    monkeypatch.setattr(
        conversation_loop,
        "get_command_with_retries",
        lambda model: "turn on the bedroom light",
    )
    monkeypatch.setattr(
        conversation_loop,
        "process_command_loop",
        lambda model,
        command,
        served_turn=False,
        wake_context_prompt=None,
        quiet_first_response=False: events.append(
            ("process", command, served_turn, wake_context_prompt, quiet_first_response)
        ),
    )

    conversation_loop.handle_command_server_instruction(object(), {"text": "Welcome home."})

    assert events == [
        ("clear",),
        ("chime",),
        ("speak", "Welcome home.", "command_server"),
        ("process", "turn on the bedroom light", False, None, True),
    ]


def test_command_server_instruction_command_timeout_is_silent(monkeypatch):
    events = []

    monkeypatch.setattr(conversation_loop, "clear_audio_queue", lambda: events.append(("clear",)))
    monkeypatch.setattr(
        conversation_loop,
        "speak",
        lambda text, model=None, kind="speech": events.append(("speak", text, kind)),
    )
    monkeypatch.setattr(
        conversation_loop,
        "play_command_server_preamble",
        lambda: events.append(("chime",)),
    )
    monkeypatch.setattr(
        conversation_loop,
        "get_command_with_retries",
        lambda model: "",
    )
    monkeypatch.setattr(
        conversation_loop,
        "confirm_standby_if_served",
        lambda served_turn, model: events.append(("standby", served_turn)),
    )

    conversation_loop.handle_command_server_instruction(object(), {"text": "Welcome home."})

    assert events == [
        ("clear",),
        ("chime",),
        ("speak", "Welcome home.", "command_server"),
    ]
