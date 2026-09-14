import subprocess
import wave

import call_agent_api
import conversation_loop
import play_audio
import text_to_speech
from call_agent_api import parse_agent_reply
from detect_wake_word import get_wake_match
from speech_to_text import calculate_rms, remove_wake_words, write_wav
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
    assert clean_for_tts("[Pasture] **Hello**   there") == "Hello there"
    assert calculate_rms(b"\x00\x00" * 20) == 0


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
    assert captured["kwargs"]["check"] is True


def test_volume_configuration_can_be_disabled(monkeypatch):
    def unexpected_run(*args, **kwargs):
        raise AssertionError("amixer should not run")

    monkeypatch.setattr(play_audio, "CONFIGURE_VOLUME", False)
    monkeypatch.setattr(play_audio.subprocess, "run", unexpected_run)
    play_audio.ensure_speaker_volume()


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
