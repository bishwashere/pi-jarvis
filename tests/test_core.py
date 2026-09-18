import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import call_agent_api
import conversation_loop
import listen_to_mic
import play_audio
import text_to_speech
from call_agent_api import parse_agent_reply
from daily_context import contextualize_affirmative_command, parse_suggestions
from detect_wake_word import get_wake_match
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
    assert remove_wake_words("hey jarvis tell me the time") == "tell me the time"
    assert clean_command_transcript("Hi.") == WAKE_ONLY_COMMAND
    assert clean_command_transcript("hello computer?") == WAKE_ONLY_COMMAND
    assert clean_command_transcript("Jarvis, what time is it?") == "what time is it"
    assert "yes" in QUICK_COMMANDS
    assert "do nothing" in QUICK_COMMANDS
    assert clean_for_tts("[Pasture] **Hello**   there") == "Hello there"
    assert calculate_rms(b"\x00\x00" * 20) == 0


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


def test_agent_request_uses_openai_compatible_payload(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            captured["checked"] = True

        def json(self):
            return {"choices": [{"message": {"content": "Hello"}}]}

    def fake_post(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return Response()

    monkeypatch.setattr(call_agent_api.requests, "post", fake_post)

    assert call_agent_api.ask_pasture("status") == {
        "reply": "Hello",
        "continue_listening": False,
    }
    assert captured["url"] == call_agent_api.API_URL
    assert captured["kwargs"]["timeout"] == 60
    assert captured["kwargs"]["json"]["messages"][-1] == {
        "role": "user",
        "content": "status",
    }
    assert captured["checked"] is True


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
    monkeypatch.setattr(conversation_loop, "speak", lambda text: None)
    monkeypatch.setattr(
        conversation_loop,
        "get_command_with_retries",
        lambda model: "what time is it",
    )
    monkeypatch.setattr(
        conversation_loop,
        "ask_and_speak",
        lambda text, model: calls.append(text) or False,
    )
    monkeypatch.setattr(
        conversation_loop,
        "listen_for_command",
        lambda model, seconds: "",
    )

    conversation_loop.handle_conversation(object())

    assert calls == ["what time is it"]
