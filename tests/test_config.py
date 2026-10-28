import json
import os
import subprocess
import sys
from pathlib import Path

import config
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_repository_paths_follow_checkout():
    assert config.PROJECT_DIR == PROJECT_ROOT
    assert Path(config.VOSK_MODEL_PATH) == (
        PROJECT_ROOT / "runtime/assets/vosk-model-small-en-us-0.15"
    )
    assert Path(config.PIPER_MODEL_PATH) == (
        PROJECT_ROOT / "runtime/assets/piper/en_US-amy-medium.onnx"
    )
    assert Path(config.COMMAND_RECORDING_PATH) == PROJECT_ROOT / "logs/command.wav"
    assert Path(config.REPLY_WAV_PATH) == PROJECT_ROOT / "logs/reply.wav"
    assert Path(config.WHISPER_CPP_BINARY) == (
        PROJECT_ROOT.parent / "whisper.cpp/build/bin/whisper-cli"
    )
    assert config.COMMAND_STT_ENGINE == "whisper"
    assert config.PLAYBACK_BACKEND == "auto"
    expected_playback_device = (
        "plughw:2,0" if sys.platform.startswith("linux") else "default"
    )
    assert config.PLAYBACK_DEVICE == expected_playback_device
    assert config.COMMAND_SERVER_PORT == 8765


def test_environment_overrides_are_parsed_in_fresh_process(tmp_path):
    script = """
import json
import config
print(json.dumps({
    "project": str(config.PROJECT_DIR),
    "model": config.VOSK_MODEL_PATH,
    "audio": config.AUDIO_DEVICE,
    "fallbacks": config.AUDIO_DEVICE_FALLBACKS,
    "backend": config.PLAYBACK_BACKEND,
    "volume": config.CONFIGURE_VOLUME,
    "command_server_port": config.COMMAND_SERVER_PORT,
}))
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("JARVIS_")
    }
    environment.update(
        {
            "PYTHONPATH": str(PROJECT_ROOT),
            "JARVIS_PROJECT_DIR": str(tmp_path),
            "JARVIS_VOSK_MODEL_PATH": "models/vosk",
            "JARVIS_AUDIO_DEVICE": "7",
            "JARVIS_AUDIO_DEVICE_FALLBACKS": "pulse,3",
            "JARVIS_PLAYBACK_BACKEND": "sounddevice",
            "JARVIS_CONFIGURE_VOLUME": "false",
            "JARVIS_COMMAND_SERVER_PORT": "9999",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    values = json.loads(result.stdout)

    assert values == {
        "project": str(tmp_path),
        "model": str(tmp_path / "models/vosk"),
        "audio": 7,
        "fallbacks": ["pulse", 3],
        "backend": "sounddevice",
        "volume": False,
        "command_server_port": 9999,
    }


def test_command_server_binds_to_lan_when_token_is_configured():
    script = """
import json
import config
print(json.dumps({
    "host": config.COMMAND_SERVER_HOST,
    "token": config.COMMAND_SERVER_TOKEN,
}))
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("JARVIS_")
    }
    environment.update(
        {
            "PYTHONPATH": str(PROJECT_ROOT),
            "JARVIS_COMMAND_SERVER_TOKEN": "secret",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "host": "0.0.0.0",
        "token": "secret",
    }


def test_command_server_explicit_host_override_is_preserved():
    script = """
import json
import config
print(json.dumps({
    "host": config.COMMAND_SERVER_HOST,
    "token": config.COMMAND_SERVER_TOKEN,
}))
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("JARVIS_")
    }
    environment.update(
        {
            "PYTHONPATH": str(PROJECT_ROOT),
            "JARVIS_COMMAND_SERVER_HOST": "127.0.0.1",
            "JARVIS_COMMAND_SERVER_TOKEN": "secret",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "host": "127.0.0.1",
        "token": "secret",
    }


@pytest.mark.skipif(os.name == "nt", reason="Raspberry Pi path invariant")
def test_pi_checkout_keeps_original_deployment_paths():
    script = """
import json
import config
print(json.dumps({
    "vosk": config.VOSK_MODEL_PATH,
    "piper": config.PIPER_MODEL_PATH,
    "whisper": config.WHISPER_CPP_BINARY,
    "reply": config.REPLY_WAV_PATH,
}))
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("JARVIS_")
    }
    environment.update(
        {
            "PYTHONPATH": str(PROJECT_ROOT),
            "JARVIS_PROJECT_DIR": "/home/<user>/jarvis",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "vosk": "/home/<user>/jarvis/runtime/assets/vosk-model-small-en-us-0.15",
        "piper": "/home/<user>/jarvis/runtime/assets/piper/en_US-amy-medium.onnx",
        "whisper": "/home/<user>/whisper.cpp/build/bin/whisper-cli",
        "reply": "/home/<user>/jarvis/logs/reply.wav",
    }


def test_windows_uses_portable_default_playback_device():
    script = """
import json
import sys
sys.platform = "win32"
import config
print(json.dumps({
    "backend": config.PLAYBACK_BACKEND,
    "device": config.PLAYBACK_DEVICE,
}))
"""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("JARVIS_")
    }
    environment["PYTHONPATH"] = str(PROJECT_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    assert json.loads(result.stdout) == {
        "backend": "auto",
        "device": "default",
    }
