import json
import os
import subprocess
import sys
from pathlib import Path

import config
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_echo_log_limits_in_fresh_process():
    env = {k: v for k, v in os.environ.items() if not k.startswith('JARVIS_')}
    env.update(JARVIS_ECHO_LOG_MAX_BYTES='1024', JARVIS_ECHO_LOG_BACKUP_COUNT='2')
    result = subprocess.run([sys.executable, '-c',
        'import config; print(config.ECHO_LOG_MAX_BYTES, config.ECHO_LOG_BACKUP_COUNT)'],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == '1024 2'
    env['JARVIS_ECHO_LOG_BACKUP_COUNT'] = '0'
    result = subprocess.run([sys.executable, '-c', 'import config'],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'must be positive' in result.stderr


@pytest.mark.parametrize("value", ["0", "-1"])
def test_speech_threshold_rejects_nonpositive_values(value):
    environment = {key: val for key, val in os.environ.items()
                   if not key.startswith("JARVIS_")}
    environment["JARVIS_COMMAND_AUDIO_RMS_THRESHOLD"] = value
    result = subprocess.run(
        [sys.executable, "-c", "import config"], cwd=PROJECT_ROOT,
        env=environment, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "JARVIS_COMMAND_AUDIO_RMS_THRESHOLD must be positive" in result.stderr


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
    assert config.COMMAND_AUDIO_RMS_THRESHOLD == 420
    assert config.PIPER_BACKEND == "cli"
    assert config.WAITING_ANNOUNCEMENTS is True
    assert config.PLAYBACK_BACKEND == "auto"
    expected_playback_device = (
        "plughw:2,0" if sys.platform.startswith("linux") else "default"
    )
    assert config.PLAYBACK_DEVICE == expected_playback_device
    assert config.COMMAND_SERVER_PORT == 8765
    assert config.LENIENT_WAKE_LEVEL == 0
    assert "hi" not in config.WAKE_WORDS
    assert "hello" in config.WAKE_WORDS
    assert "hey" not in config.WAKE_WORDS
    assert "hey jarvis" in config.WAKE_WORDS


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
    "profiles": config.SPEAKER_PROFILES_PATH,
    "profile_volume_overrides": config.SPEAKER_VOLUME_OVERRIDES,
    "command_server_port": config.COMMAND_SERVER_PORT,
    "echo": [config.ECHO_BIND, config.ECHO_PORT, config.ECHO_DEVICE_ID, config.ECHO_TOKEN],
    "wake": [config.WAKE_WORDS, config.LENIENT_WAKE_LEVEL],
    "native_wake": [config.ECHO_NATIVE_WAKE, config.ECHO_WAKE_THRESHOLD],
    "piper_backend": config.PIPER_BACKEND,
    "speech_threshold": config.COMMAND_AUDIO_RMS_THRESHOLD,
    "waiting_announcements": config.WAITING_ANNOUNCEMENTS,
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
            "JARVIS_SPEAKER_PROFILES_PATH": "speakers/custom.json",
            "JARVIS_VOLUME_LEVEL": "40%",
            "JARVIS_COMMAND_SERVER_PORT": "9999",
            "JARVIS_ECHO_BIND": "192.0.2.10",
            "JARVIS_ECHO_PORT": "8877",
            "JARVIS_ECHO_DEVICE_ID": "test-dot",
            "JARVIS_ECHO_TOKEN": "test-token",
            "JARVIS_WAKE_WORDS": " Hey   Jarvis, Computer ",
            "JARVIS_LENIENT_WAKE_LEVEL": "20",
            "JARVIS_ECHO_NATIVE_WAKE": "true",
            "JARVIS_ECHO_WAKE_THRESHOLD": "0.6",
            "JARVIS_PIPER_BACKEND": "python",
            "JARVIS_COMMAND_AUDIO_RMS_THRESHOLD": "1000",
            "JARVIS_WAITING_ANNOUNCEMENTS": "false",
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
        "profiles": str(tmp_path / "speakers/custom.json"),
        "profile_volume_overrides": {"level": "40%"},
        "command_server_port": 9999,
        "echo": ["192.0.2.10", 8877, "test-dot", "test-token"],
        "wake": [["hey jarvis", "computer"], 20],
        "native_wake": [True, 0.6],
        "piper_backend": "python",
        "speech_threshold": 1000,
        "waiting_announcements": False,
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


@pytest.mark.parametrize('value,valid', [('1.5', True), ('0', False), ('-1', False), ('nan', False), ('inf', False), ('11', False)])
def test_silence_window_override(value, valid):
    environment = {k: v for k, v in os.environ.items() if not k.startswith('JARVIS_')}
    environment['JARVIS_COMMAND_SILENCE_SECONDS'] = value
    result = subprocess.run([sys.executable, '-c', 'import config; print(config.COMMAND_SILENCE_SECONDS)'],
                            cwd=PROJECT_ROOT, env=environment, text=True, capture_output=True)
    assert (result.returncode == 0) is valid
    if valid:
        assert float(result.stdout.strip()) == 1.5
    else:
        assert 'JARVIS_COMMAND_SILENCE_SECONDS must be' in result.stderr


@pytest.mark.parametrize('port,valid', [('16701', True), ('0', False), ('65536', False)])
def test_hassmic_config_in_fresh_process(port, valid):
    environment = {k: v for k, v in os.environ.items() if not k.startswith('JARVIS_')}
    environment.update(JARVIS_HASSMIC_HOST='192.0.2.1', JARVIS_HASSMIC_PORT=port)
    result = subprocess.run([sys.executable, '-c', 'import config; print(config.HASSMIC_HOST, config.HASSMIC_PORT)'],
                            cwd=PROJECT_ROOT, env=environment, text=True, capture_output=True)
    assert (result.returncode == 0) is valid
    if valid:
        assert result.stdout.strip() == '192.0.2.1 16701'


def test_voice_profile_override_in_fresh_process(tmp_path):
    environment = {key: val for key, val in os.environ.items() if not key.startswith('JARVIS_')}
    environment['JARVIS_VOICE_PROFILE_DIR'] = str(tmp_path/'profiles')
    result = subprocess.run([sys.executable, '-c', 'import config; print(config.VOICE_PROFILE_DIR)'],
                            cwd=PROJECT_ROOT, env=environment, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == str(tmp_path/'profiles')


@pytest.mark.parametrize('name', ['JARVIS_HASSMIC_WAKE_WAIT_SECONDS', 'JARVIS_HASSMIC_FOLLOWUP_WAIT_SECONDS'])
@pytest.mark.parametrize('value,valid', [('5',True),('0',False),('61',False),('nan',False)])
def test_echo_no_speech_wait_override(name,value,valid):
    import subprocess
    import sys
    import os
    result=subprocess.run([sys.executable,'-c',
        f'import config; print(config.{name.removeprefix("JARVIS_")})'],
        env=dict(os.environ,**{name:value}),capture_output=True,text=True)
    assert (result.returncode==0)==valid
    if valid: assert result.stdout.strip()=='5.0'


def test_echo_registry_path_resolves_from_checkout_in_fresh_process(tmp_path):
    result = subprocess.run([sys.executable, '-c', 'import config; print(config.ECHO_DEVICES_PATH)'],
        env=dict(os.environ, JARVIS_PROJECT_DIR=str(tmp_path), JARVIS_ECHO_DEVICES_PATH='devices.json'),
        capture_output=True, text=True, check=True)
    assert result.stdout.strip() == str(tmp_path / 'devices.json')
