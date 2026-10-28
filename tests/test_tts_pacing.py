import os
import subprocess
import sys
import wave
from types import SimpleNamespace

import pytest

import text_to_speech as tts


@pytest.mark.parametrize('source, expected', [
    ('I’m good—ready when you are.', "I'm good, ready when you are."),
    ('“It’s ready; don’t worry.”', "It's ready; don't worry."),
    ('The meeting is at 3:30. It costs $3.50.', 'The meeting is at 3:30. It costs $3.50.'),
    ('Wait 30–45 minutes—then check.', 'Wait 30 to 45 minutes, then check.'),
    ('Use a well-tested tool. It is -3 degrees.', 'Use a well-tested tool. It is -3 degrees.'),
    ('[Jarvis] **Ready!** Are you? Yes: let’s go.', "Ready! Are you? Yes: let's go."),
])
def test_cleanup_preserves_speech_punctuation(source, expected):
    assert tts.clean_for_tts(source) == expected


@pytest.mark.parametrize('platform', ['linux', 'win32'])
@pytest.mark.parametrize('gap', [.15, .25])
@pytest.mark.parametrize('chunk_count', [1, 3])
def test_sentence_gaps_preserve_pcm_and_have_no_leading_or_trailing_padding(
        monkeypatch, tmp_path, platform, gap, chunk_count):
    rate = 22050
    chunks = [bytes([index + 1, 0]) * 40 for index in range(chunk_count)]
    loads, calls = [], []
    class Voice:
        def synthesize(self, text, syn_config):
            calls.append((text, syn_config.length_scale))
            for pcm in chunks:
                yield SimpleNamespace(sample_channels=1, sample_width=2,
                                      sample_rate=rate, audio_int16_bytes=pcm)
    monkeypatch.setattr(tts.sys, 'platform', platform)
    monkeypatch.setattr(tts, 'PIPER_BACKEND', 'python')
    monkeypatch.setattr(tts, 'PIPER_SENTENCE_SILENCE', gap)
    monkeypatch.setattr(tts, 'PIPER_LENGTH_SCALE', 1.08)
    monkeypatch.setattr(tts, '_cached_voice', None)
    monkeypatch.setitem(sys.modules, 'piper', SimpleNamespace(
        PiperVoice=SimpleNamespace(load=lambda path: loads.append(path) or Voice()),
        SynthesisConfig=SimpleNamespace))
    for index in range(2):
        path = tmp_path / f'{index}.wav'
        tts.synthesize_to_wav('I’m good. Ready when you are.', str(path))
        with wave.open(str(path)) as wav:
            assert wav.getparams()[:3] == (1, 2, rate)
            expected = bytes(int(rate * gap) * 2).join(chunks)
            assert wav.readframes(wav.getnframes()) == expected
            assert wav.getnframes() == 40 * chunk_count + int(rate * gap) * (chunk_count - 1)
    assert len(loads) == 1
    assert calls == [("I'm good. Ready when you are.", 1.08)] * 2


@pytest.mark.parametrize('platform', ['linux', 'win32'])
@pytest.mark.parametrize('gap', [0, .25])
def test_cli_uses_same_gap_and_normalized_text(monkeypatch, tmp_path, platform, gap):
    calls = []
    monkeypatch.setattr(tts.sys, 'platform', platform)
    monkeypatch.setattr(tts, 'PIPER_BACKEND', 'cli')
    monkeypatch.setattr(tts, 'PIPER_SENTENCE_SILENCE', gap)
    monkeypatch.setattr(tts, 'resolve_piper_binary', lambda: 'piper.exe' if platform == 'win32' else 'piper')
    monkeypatch.setattr(tts.subprocess, 'run', lambda args, **kwargs: calls.append((args, kwargs)))
    tts.synthesize_to_wav('I’m good—ready when you are.', str(tmp_path / 'output.wav'))
    args, kwargs = calls[0]
    assert kwargs['input'] == "I'm good, ready when you are."
    if gap:
        assert args[args.index('--sentence-silence') + 1] == str(gap)
    else:
        assert '--sentence-silence' not in args


@pytest.mark.parametrize('value, expected', [(None, '.25'), ('0', '0'), ('0.4', '.4'),
                                         ('-1', None), ('2.1', None), ('nan', None), ('inf', None)])
def test_sentence_gap_configuration_in_fresh_process(value, expected):
    env = dict(os.environ)
    env.pop('JARVIS_PIPER_SENTENCE_SILENCE', None)
    if value is not None:
        env['JARVIS_PIPER_SENTENCE_SILENCE'] = value
    result = subprocess.run([sys.executable, '-c', 'import config; print(config.PIPER_SENTENCE_SILENCE)'],
                            env=env, text=True, capture_output=True)
    assert (result.returncode == 0) is (expected is not None)
    if expected is not None:
        assert float(result.stdout.strip()) == float(expected)


def test_empty_piper_output_still_has_valid_wav_header(monkeypatch, tmp_path):
    voice = SimpleNamespace(config=SimpleNamespace(sample_rate=22050), synthesize=lambda text: iter(()))
    monkeypatch.setattr(tts, 'PIPER_BACKEND', 'python')
    monkeypatch.setattr(tts, 'PIPER_LENGTH_SCALE', None)
    monkeypatch.setattr(tts, 'PIPER_SENTENCE_SILENCE', .25)
    monkeypatch.setattr(tts, '_cached_voice', None)
    monkeypatch.setitem(sys.modules, 'piper', SimpleNamespace(PiperVoice=SimpleNamespace(load=lambda _: voice)))
    path = tmp_path / 'empty.wav'
    tts.synthesize_to_wav('...', str(path))
    with wave.open(str(path)) as wav:
        assert wav.getnframes() == 0
        assert wav.getframerate() == 22050
