"""Local controls must stop capture without delegating that decision to the agent."""
import wave
from types import SimpleNamespace

import pytest

import call_agent_api
import conversation_loop as conversation
import hassmic_jarvis as bridge


@pytest.mark.parametrize('text', [
    'stop', 'cancel', 'goodbye', 'never mind', 'nothing',
    'Computer, stop listening.', 'Hey Jarvis, be quiet please.',
    'Please stop talking, Jarvis.', 'silence', 'quiet', 'shut up',
    "That's enough", 'end the conversation', 'stop responding',
])
def test_silence_phrases_match(text):
    assert conversation.is_end_session_command(text)


@pytest.mark.parametrize('text', ['stand down', 'Computer, stand down.',
                                'Please stand down for one hour, Jarvis.',
                                'Hey Jarvis, stand down please'])
def test_stand_down_phrases_match(text):
    assert conversation.is_stand_down_command(text)


@pytest.mark.parametrize('text', ['stop the music', 'cancel the timer',
                                'what does stand down mean', 'please be quiet for the movie review',
                                'thank you', 'do not stop listening'])
def test_other_requests_are_not_silence_controls(text):
    assert not conversation.is_end_session_command(text)
    assert not conversation.is_stand_down_command(text)


def synthesize(text, path):
    with wave.open(path, 'wb') as output:
        output.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
        output.writeframes(bytes(200))
    return path


def control_wire(monkeypatch, text, followup):
    monkeypatch.setattr(conversation, '_stand_down_until', 0)
    sent, events, captures, asked = [], [], [], []
    incoming = [('info', {'satellite': {'supports_jarvis_followup': True}}, b'')]
    transcripts = []
    if followup:
        incoming += [('run-pipeline', {'start_stage': 'asr'}, b''), ('played', {}, b'')]
        transcripts.append('what is two plus two')
    incoming += [('run-pipeline', {'start_stage': 'asr'}, b''), ('played', {}, b'')]
    transcripts.append(text)
    incoming, transcripts = iter(incoming), iter(transcripts)
    def receive():
        try:
            return next(incoming)
        except StopIteration:
            raise EOFError('end test')
    def send(*args, **kwargs):
        sent.append((args, kwargs))
    def capture(*args, **kwargs):
        captures.append(True)
        send('transcript', {'text': ''})
        return True
    def ask(text):
        asked.append(text)
        assert text == 'what is two plus two', 'Local control reached the agent'
        return {'reply': 'four', 'continue_listening': False}
    monkeypatch.setattr(bridge, 'capture', capture)
    monkeypatch.setattr(bridge, 'voice_event', lambda name, **data: events.append((name, data)))
    wire = SimpleNamespace(send=send, next_event=receive,
                           sock=SimpleNamespace(settimeout=lambda _: None))
    return wire, lambda _: next(transcripts), ask, sent, events, captures, asked


@pytest.mark.parametrize('followup', [False, True])
@pytest.mark.parametrize('text', ['stop', 'Computer, stop listening.', 'Please be quiet, Jarvis.', 'cancel'])
def test_silence_ends_capture_before_session_reset(tmp_path, monkeypatch, text, followup):
    wire, transcribe, ask, sent, events, captures, asked = control_wire(monkeypatch, text, followup)
    resets = []
    def reset():
        assert sent[-1][0] == ('error', {'code': 'stt-no-text-recognized'})
        resets.append(True)
    monkeypatch.setattr(call_agent_api, 'start_new_pasture_session', reset)
    with pytest.raises(EOFError):
        bridge.serve(wire, transcribe, ask, synthesize, tmp_path)
    assert resets == [True]
    assert len(captures) == 1 + followup
    assert len(asked) == followup
    # No silence acknowledgement or new follow-up window is sent.
    stops = [args for args, _ in sent if args[0] == 'audio-stop']
    assert len(stops) == followup
    assert events[-1][0] == 'wake_listen_started'
    assert any(name == 'session_end_command' for name, _ in events)


@pytest.mark.parametrize('followup', [False, True])
def test_stand_down_pauses_wakes_and_announcements_then_resumes(tmp_path, monkeypatch, followup):
    wire, transcribe, ask, sent, events, captures, asked = control_wire(
        monkeypatch, 'Computer, stand down.', followup)
    now = [1000.0]
    monkeypatch.setattr(conversation.time, 'time', lambda: now[0])
    monkeypatch.setattr(bridge, 'STAND_DOWN_SECONDS', 3600)
    announcements = bridge.Announcements()
    pending = [('ping', {}, b''), ('run-pipeline', {'start_stage': 'asr'}, b'')]
    ready_calls = []
    def ready(timeout):
        ready_calls.append(timeout)
        if conversation.stand_down_remaining() == 0:
            return True
        if pending:
            return True
        # Queued announcements must remain queued during stand-down.
        assert announcements.pending.qsize() == 1
        now[0] = 4601
        return False
    def receive():
        assert conversation.stand_down_remaining() > 0
        return pending.pop(0)
    wire.ready, wire.receive = ready, receive
    announcements.handle({'text': 'An announcement'})
    with pytest.raises(EOFError):
        bridge.serve(wire, transcribe, ask, synthesize, tmp_path, announcements=announcements)
    controls = [args for args, _ in sent]
    assert ('audio-stop', {'jarvis_followup': 0}) in controls
    assert controls.count(('pause-satellite',)) == 2  # command, then raced wake
    assert controls.count(('run-satellite',)) == 2  # startup and timer expiry
    assert ('pong',) in controls
    assert len(captures) == 1 + followup
    assert len(asked) == followup
    assert announcements.pending.qsize() == 1
    assert any(name == 'hassmic_wake_ignored' for name, _ in events)
    assert any(name == 'hassmic_stand_down_finished' for name, _ in events)


def test_reconnection_during_stand_down_never_enables_wake(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation, '_stand_down_until', float('inf'))
    sent = []
    def disconnected(timeout):
        raise EOFError('disconnected while paused')
    wire = SimpleNamespace(send=lambda *args: sent.append(args),
                           next_event=lambda: ('info', {'satellite': {'supports_jarvis_followup': True}}, b''),
                           ready=disconnected, sock=SimpleNamespace(settimeout=lambda _: None))
    with pytest.raises(EOFError):
        bridge.serve(wire, None, None, None, tmp_path)
    assert sent == [('describe',), ('pause-satellite',)]


def test_stand_down_still_pauses_if_confirmation_fails(tmp_path, monkeypatch):
    wire, transcribe, ask, sent, events, captures, asked = control_wire(monkeypatch, 'stand down', False)
    def broken_synthesis(*args):
        raise RuntimeError('Piper unavailable')
    with pytest.raises(RuntimeError, match='Piper unavailable'):
        bridge.serve(wire, transcribe, ask, broken_synthesis, tmp_path)
    assert sent[-1][0] == ('pause-satellite',)
    assert conversation.stand_down_remaining() > 0
    assert not asked
