import sys
import wave
from types import SimpleNamespace

import pytest

import text_to_speech


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_python_voice_is_reused_and_reloads_for_changed_model(monkeypatch, tmp_path, platform):
    monkeypatch.setattr(text_to_speech, 'PIPER_SENTENCE_SILENCE', 0)
    loads, spoken = [], []

    class Voice:
        def synthesize_wav(self, text, output):
            spoken.append(text)
            output.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            output.writeframes(b"\x00\x00" * 40)

    monkeypatch.setattr(text_to_speech.sys, "platform", platform)
    monkeypatch.setattr(text_to_speech, "PIPER_BACKEND", "python")
    monkeypatch.setattr(text_to_speech, "_cached_voice", None)
    monkeypatch.setattr(text_to_speech, "_cached_model_path", None)
    monkeypatch.setattr(text_to_speech, "PIPER_MODEL_PATH", str(tmp_path / "first.onnx"))
    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(PiperVoice=SimpleNamespace(
        load=lambda model: loads.append(model) or Voice(),
    )))
    monkeypatch.setattr(text_to_speech.subprocess, "run",
                        lambda *a, **kw: pytest.fail("Python backend must not start a process"))
    for index, text in enumerate(["**First**", "Second"]):
        path = tmp_path / "nested" / f"{index}.wav"
        assert text_to_speech.synthesize_to_wav(text, str(path)) == str(path)
        with wave.open(str(path)) as audio:
            assert audio.getnframes() == 40
    assert len(loads) == 1
    assert spoken == ["First", "Second"]
    monkeypatch.setattr(text_to_speech, "PIPER_MODEL_PATH", str(tmp_path / "second.onnx"))
    text_to_speech.synthesize_to_wav("Third", str(tmp_path / "third.wav"))
    assert loads == [str(tmp_path / "first.onnx"), str(tmp_path / "second.onnx")]


def test_failed_model_load_is_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(text_to_speech, "PIPER_BACKEND", "python")
    monkeypatch.setattr(text_to_speech, "_cached_voice", None)
    monkeypatch.setattr(text_to_speech, "_cached_model_path", None)

    def fail(model):
        raise RuntimeError("model unavailable")

    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(
        PiperVoice=SimpleNamespace(load=fail),
    ))
    with pytest.raises(RuntimeError, match="model unavailable"):
        text_to_speech.synthesize_to_wav("Hello", str(tmp_path / "reply.wav"))
    assert text_to_speech._cached_voice is None


@pytest.mark.parametrize('backend', ['python', 'cli'])
@pytest.mark.parametrize('platform', ['linux', 'win32'])
def test_slightly_slower_voice_on_both_backends(monkeypatch, tmp_path, backend, platform):
    monkeypatch.setattr(text_to_speech, 'PIPER_SENTENCE_SILENCE', 0)
    seen = []
    class Voice:
        def synthesize_wav(self, text, output, syn_config):
            seen.append(syn_config.length_scale)
            output.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            output.writeframes(b'\0\0' * 40)
    monkeypatch.setattr(text_to_speech.sys, 'platform', platform)
    monkeypatch.setattr(text_to_speech, 'PIPER_BACKEND', backend)
    monkeypatch.setattr(text_to_speech, 'PIPER_LENGTH_SCALE', 1.08)
    monkeypatch.setattr(text_to_speech, '_cached_voice', None)
    monkeypatch.setitem(sys.modules, 'piper', SimpleNamespace(
        PiperVoice=SimpleNamespace(load=lambda _: Voice()), SynthesisConfig=SimpleNamespace))
    monkeypatch.setattr(text_to_speech, 'resolve_piper_binary', lambda: 'piper')
    monkeypatch.setattr(text_to_speech.subprocess, 'run', lambda args, **kw: seen.append(args))
    text_to_speech.synthesize_to_wav('A little slower.', str(tmp_path/'speech.wav'))
    if backend == 'python':
        assert seen == [1.08]
    else:
        assert seen[0][-2:] == ['--length_scale', '1.08']


@pytest.mark.parametrize('value, valid', [('1.08', True), ('', True), ('0', False), ('nan', False)])
def test_speed_configuration_in_fresh_process(value, valid):
    import os
    import subprocess
    env = dict(os.environ, JARVIS_PIPER_LENGTH_SCALE=value)
    proc = subprocess.run([sys.executable, '-c', 'import config; print(config.PIPER_LENGTH_SCALE)'],
                          env=env, capture_output=True, text=True)
    assert (proc.returncode == 0) is valid
    if valid:
        assert proc.stdout.strip() == (value or 'None')
