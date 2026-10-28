"""Local primary-user enrollment. Collection is not model training or enrollment of identity."""
import json
import os
import re
import time
import wave
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from config import VOICE_PROFILE_DIR
from voice_log import voice_event


def normalized(text):
    words = ' '.join(re.findall(r'[a-z0-9]+', text.lower()))
    return re.sub(r'\bset up\b', 'setup', words)


def is_setup_command(text):
    words = normalized(text)
    for prefix in ('hey jarvis ', 'jarvis ', 'computer '):
        if words.startswith(prefix):
            words = words[len(prefix):]
            break
    phrase = r'(?:do setup|start voice setup|start setup|setup my voice)'
    # Repeated attempts in one recording are still one local setup request.
    # Anchor the whole utterance so questions about setup are not intercepted.
    return re.fullmatch(rf'{phrase}(?: {phrase}){{0,2}}', words) is not None


def is_cancel_command(text):
    phrase = r'(?:cancel setup|stop setup)'
    return re.fullmatch(rf'{phrase}(?: {phrase}){{0,2}}', normalized(text)) is not None


def save_json(path, data):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        os.chmod(temporary, 0o600)
        json.dump(data, output, indent=2)
    temporary.replace(path)


def record_window(wire, path, seconds):
    """Keep quiet/far speech too. Do not gate enrollment on production VAD."""
    from speech_to_text import calculate_rms
    frames, levels = [], []
    remaining = int(seconds * 32000)
    deadline = time.monotonic() + seconds + 10
    while remaining > 0:
        if time.monotonic() > deadline:
            raise TimeoutError('Setup audio stream stalled')
        kind, data, pcm = wire.next_event()
        if kind == 'run-pipeline':
            raise RuntimeError('Setup interrupted by a new pipeline')
        if kind != 'audio-chunk':
            continue
        if (data.get('rate'), data.get('width'), data.get('channels')) != (16000, 2, 1) or len(pcm) % 2:
            raise ValueError('Setup requires mono 16 kHz signed 16-bit PCM')
        pcm = pcm[:remaining]
        frames.append(pcm)
        remaining -= len(pcm)
    wire.send('transcript', {'text': ''})
    audio = b''.join(frames)
    # Fixed 30 ms blocks make measurements independent of network chunk size.
    levels = [calculate_rms(audio[i:i+960]) for i in range(0, len(audio), 960)]
    with path.open('wb') as output:
        os.chmod(path, 0o600)
        with wave.open(output, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(audio)
    ordered = sorted(levels)
    return {'seconds': seconds, 'rms_peak': max(levels, default=0),
            'rms_p90': ordered[int(.9 * (len(ordered)-1))] if ordered else 0}


def run_setup(wire, transcribe, synthesize, play, *, root=None):
    root = Path(root or VOICE_PROFILE_DIR) / 'primary'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    session = root / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
    session.mkdir(mode=0o700)
    manifest = {'user': 'primary', 'status': 'collecting', 'model_status': 'not_trained',
                'settings_applied': False, 'samples': [], 'created': datetime.now().isoformat(),
                'audio_source': 'Echo Wyoming command stream, post audio front end'}
    target = session / 'profile.json'
    save_json(target, manifest)

    def say(text, listen):
        path = synthesize(text, str(session / 'prompt.wav'))
        play(wire, path, followup=listen)
        if listen:
            kind, data, _ = wire.next_event()
            if kind != 'run-pipeline' or data.get('start_stage') != 'asr':
                raise RuntimeError('Echo did not begin setup recording')

    def sample(label, prompt, seconds, expected=None):
        say(prompt, True)
        voice_event('voice_setup_recording', user='primary', sample=label, seconds=seconds)
        path = session / f'{label}.wav'
        stats = record_window(wire, path, seconds)
        text = transcribe(str(path)) if expected is not None else None
        entry = {'label': label, 'file': path.name, 'expected': expected,
                 'transcript': text, **stats}
        # Whisper is only a review aid, not ground truth for wake-word labels.
        entry['needs_review'] = expected is not None
        manifest['samples'].append(entry)
        save_json(target, manifest)
        voice_event('voice_setup_sample_saved', sample=label, rms_peak=stats['rms_peak'])
        if text and is_cancel_command(text):
            raise SetupCancelled
        return text

    try:
        sample('close_noise', 'Voice setup saves recordings on this Pi for the primary user. '
               'Say cancel setup during a speaking step to stop. Stay close and remain quiet for three seconds.', 3)
        phrases = [('computer', 'Computer'), ('jarvis', 'Hey Jarvis'),
                   ('lights', 'Please turn on the living room lights'),
                   ('question', 'What is the weather like today')]
        for position, location in (('close', 'close to the Echo'),
                                   ('far', 'the farther place where you normally speak'),
                                   ('side', 'a different spot off to one side of the Echo')):
            if position != 'close':
                ready = sample(f'move_{position}', f'Move to {location}. '
                               'You have fifteen seconds. Say ready when you are there.', 15, 'ready')
                if not ready or 'ready' not in normalized(ready).split() or 'not' in normalized(ready).split():
                    raise SetupCancelled
                sample(f'{position}_noise', 'Stay there and remain quiet for three seconds.', 3)
            for label, phrase in phrases:
                seconds = 14 if label in {'lights', 'question'} else 8
                duration = 'fourteen' if seconds == 14 else 'eight'
                prompt = f'Stay where you are. After I finish, say: {phrase}. Pause, then repeat it once. You have {duration} seconds.'
                sample(f'{position}_{label}', prompt, seconds, phrase)
        manifest['status'] = 'collected_needs_review'
        manifest['note'] = ('Recordings require segmentation, label review, separate held-out tests and '
                            'wake-stream compatibility checks before training. No detector or VAD settings changed.')
        save_json(target, manifest)
        save_json(root / 'latest.json', {'session': session.name, 'status': manifest['status']})
        say('Your recordings from all three positions are saved. No model has been trained or settings changed yet. '
            'We will check these recordings before tuning your voice profile. Setup is finished.', False)
        voice_event('voice_setup_finished', user='primary', profile=target)
    except SetupCancelled:
        manifest['status'] = 'cancelled'
        save_json(target, manifest)
        say('Setup stopped. Partial recordings are saved. Your existing settings are unchanged.', False)
        voice_event('voice_setup_cancelled', user='primary', profile=target)
    except Exception as error:
        manifest['status'] = 'interrupted'
        manifest['error'] = type(error).__name__
        save_json(target, manifest)
        voice_event('voice_setup_interrupted', user='primary', error=error, profile=target)
        raise
    finally:
        (session / 'prompt.wav').unlink(missing_ok=True)
    return manifest


class SetupCancelled(Exception):
    pass
