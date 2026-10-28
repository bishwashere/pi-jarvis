import pytest
from scripts.check_public_files import blocked_path


@pytest.mark.parametrize('name', ['.env','.env.production','.ssh_askpass','.aws/credentials',
    'logs/turn.txt','runtime/cache/recording.raw','runtime/venv/bin/python',
    'echo_devices.json','speaker_profiles.json','private.pem','archive/tests/test.wav',
    'archive/backups/script.py.bak.2026','service-credentials.json'])
def test_private_paths_are_blocked(name):
    assert blocked_path(name)


@pytest.mark.parametrize('name', ['.env.example','echo_devices.example.json',
    'speaker_profiles.example.json','runtime/assets/piper/voice.onnx','config.py'])
def test_public_examples_and_required_model_assets_allowed(name):
    assert not blocked_path(name)
