import json
import wave
from types import SimpleNamespace

import pytest

import voice_setup as setup


@pytest.mark.parametrize('text', ['do setup', 'Computer, do setup.', 'Hey Jarvis, start voice setup', 'set up my voice',
                                 'do set up.', 'do set up do set up', 'Computer, do set up.',
                                 'start voice set up', 'do setup do set up'])
def test_setup_intent(text):
    assert setup.is_setup_command(text)


@pytest.mark.parametrize('text', ['how do setup commands work', 'turn on the lights', 'computer science setup',
                                 'do set up the lights', 'do setup and turn on the lights'])
def test_not_setup_intent(text):
    assert not setup.is_setup_command(text)


@pytest.mark.parametrize('text', ['cancel set up', 'stop set up.', 'cancel setup cancel set up'])
def test_cancel_spelling_and_repetition(text):
    assert setup.is_cancel_command(text)


def test_record_keeps_quiet_audio_and_uses_exact_duration(tmp_path):
    sent = []
    wire = SimpleNamespace(next_event=lambda: ('audio-chunk', {'rate':16000,'width':2,'channels':1}, bytes(3200)),
                           send=lambda *args: sent.append(args))
    path = tmp_path/'sample.wav'
    stats = setup.record_window(wire, path, .15)
    with wave.open(str(path)) as wav:
        assert wav.getnframes() == 2400
    assert stats['rms_peak'] == 0
    assert sent == [('transcript', {'text': ''})]


def test_invalid_pcm_does_not_save_sample(tmp_path):
    wire = SimpleNamespace(next_event=lambda: ('audio-chunk', {'rate':48000,'width':2,'channels':1}, bytes(3200)))
    with pytest.raises(ValueError):
        setup.record_window(wire, tmp_path/'invalid.wav', 1)
    assert not (tmp_path/'invalid.wav').exists()


def flow(tmp_path, monkeypatch, response=lambda _: 'ready', fail=False):
    monkeypatch.setattr(setup, 'VOICE_PROFILE_DIR', str(tmp_path))
    def record(wire, path, seconds):
        if fail:
            raise EOFError('disconnected')
        path.write_bytes(b'fixture')
        return {'rms_peak':100, 'rms_p90':80, 'seconds':seconds}
    monkeypatch.setattr(setup, 'record_window', record)
    wire = SimpleNamespace(next_event=lambda: ('run-pipeline', {'start_stage':'asr'}, b''))
    prompts = []
    def synth(text, path):
        prompts.append(text)
        return path
    result = setup.run_setup(wire, response, synth, lambda *a, **kw: None)
    return result, prompts


def test_all_locations_both_words_saved_without_claiming_training(tmp_path, monkeypatch):
    result, prompts = flow(tmp_path, monkeypatch)
    labels = {sample['label'] for sample in result['samples']}
    assert all(f'{position}_{word}' in labels for position in ['close','far','side'] for word in ['computer','jarvis'])
    assert result['status'] == 'collected_needs_review'
    assert result['model_status'] == 'not_trained'
    assert not result['settings_applied']
    latest = json.loads((tmp_path/'primary/latest.json').read_text())
    saved = json.loads((tmp_path/'primary'/latest['session']/'profile.json').read_text())
    assert saved == result
    assert 'No model has been trained' in prompts[-1]
    for entry in result['samples']:
        if entry['label'].endswith(('_lights', '_question')):
            assert entry['seconds'] == 14
        elif entry['label'].endswith(('_computer', '_jarvis')):
            assert entry['seconds'] == 8
    assert sum(prompt.startswith('Move to ') for prompt in prompts) == 2
    assert sum(prompt.startswith('Stay where you are.') for prompt in prompts) == 12


def test_cancel_does_not_replace_previous_profile(tmp_path, monkeypatch):
    root=tmp_path/'primary'; root.mkdir()
    (root/'latest.json').write_text('{"session":"previous"}')
    result, _ = flow(tmp_path, monkeypatch, response=lambda _: 'Cancel setup.')
    assert result['status'] == 'cancelled'
    assert json.loads((root/'latest.json').read_text()) == {'session':'previous'}


def test_disconnect_preserves_incomplete_profile(tmp_path, monkeypatch):
    with pytest.raises(EOFError):
        flow(tmp_path, monkeypatch, fail=True)
    profiles = list((tmp_path/'primary').glob('*/profile.json'))
    assert len(profiles) == 1
    assert json.loads(profiles[0].read_text())['status'] == 'interrupted'
    assert not (tmp_path/'primary/latest.json').exists()
