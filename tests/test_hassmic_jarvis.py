import io
import json
import socket
import threading
import wave
from types import SimpleNamespace

import pytest

import hassmic_jarvis as bridge


def test_three_turns_one_wake_over_socket(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(bridge, 'voice_event', lambda name, **kw: events.append(name))
    client, satellite = socket.socketpair()
    client.settimeout(3)
    satellite.settimeout(3)
    controller = bridge.Wire(client)
    peer = bridge.Wire(satellite)
    failures = []
    received = []
    def echo():
        try:
            assert peer.next_event()[0] == 'describe'
            peer.send('info', {'satellite': {'supports_jarvis_followup': True}})
            assert peer.next_event()[0] == 'run-satellite'
            for turn in range(3):
                # Waiting for the next wake/follow-up must not inherit the
                # active exchange timeout and terminate an idle assistant.
                import time
                time.sleep(.05)
                assert client.gettimeout() is None
                peer.send('run-pipeline', {'start_stage': 'asr', 'end_stage': 'tts'})
                peer.send('audio-chunk', {'rate': 16000, 'width': 2, 'channels': 1}, b'\xd0\x07' * 2560)
                # At least the configured endpoint's worth of silence.
                for _ in range(23):
                    peer.send('audio-chunk', {'rate': 16000, 'width': 2, 'channels': 1}, bytes(3200))
                while True:
                    kind, data, pcm = peer.next_event()
                    received.append((kind, data, len(pcm)))
                    if kind == 'audio-stop':
                        assert data['jarvis_followup'] == 1
                        peer.send('played')
                        break
        except BaseException as exc:
            failures.append(exc)
    worker = threading.Thread(target=echo, daemon=True)
    worker.start()
    texts = iter(['what is 2 plus 2', 'add three to that', 'now multiply that by 2'])
    calls = []
    answers = iter(['4', '7', '14'])
    def transcribe(path):
        with wave.open(path) as audio:
            assert audio.getframerate() == 16000
            assert audio.getnframes() > 16000
        return next(texts)
    def ask(text):
        calls.append(text)
        return {'reply': next(answers), 'continue_listening': False}
    def synthesize(text, path):
        with wave.open(path, 'wb') as audio:
            audio.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            audio.writeframes(bytes(2205 * 2))
        return path
    try:
        bridge.serve(controller, transcribe, ask, synthesize, tmp_path, max_turns=3)
        worker.join(3)
        assert not worker.is_alive()
        assert not failures
        assert calls == ['what is 2 plus 2', 'add three to that', 'now multiply that by 2']
        assert sum(kind == 'audio-stop' for kind, _, _ in received) == 3
        assert events.count('wake_heard') == 1
        assert events.count('wake_listen_started') == 1
    finally:
        controller.close()
        peer.close()


@pytest.mark.parametrize('header', [
    {'type': 'audio-chunk', 'payload_length': -1},
    {'type': 'audio-chunk', 'payload_length': 2**30},
    {'type': 'info', 'data_length': 9000},
    {'type': 'info', 'data_length': True},
])
def test_wire_rejects_invalid_lengths(header):
    wire = bridge.Wire.__new__(bridge.Wire)
    wire.reader = io.BytesIO(json.dumps(header).encode() + b'\n')
    with pytest.raises(ValueError):
        wire.receive()


def test_wire_rejects_truncated_payload():
    wire = bridge.Wire.__new__(bridge.Wire)
    wire.reader = io.BytesIO(b'{"type":"audio-chunk","payload_length":4}\nxx')
    with pytest.raises(EOFError):
        wire.receive()


def test_no_speech_does_not_make_recording(tmp_path):
    sent = []
    wire = SimpleNamespace(next_event=lambda: ('audio-chunk', {'rate': 16000, 'width': 2, 'channels': 1}, bytes(3200)),
                           send=lambda *args: sent.append(args))
    path = tmp_path/'silent.wav'
    assert not bridge.capture(wire, path, .2)
    assert not path.exists()
    assert sent == [('error', {'code': 'stt-no-text-recognized'})]


def test_incompatible_satellite_fails_before_starting(tmp_path):
    sent = []
    wire = SimpleNamespace(next_event=lambda: ('info', {'satellite': {}}, b''), send=lambda *args: sent.append(args))
    with pytest.raises(RuntimeError, match='follow-up patch'):
        bridge.serve(wire, None, None, None, tmp_path)
    assert sent == [('describe',)]


def test_wrong_audio_format_rejected(tmp_path):
    wire = SimpleNamespace(next_event=lambda: ('audio-chunk', {'rate': 48000, 'width': 2, 'channels': 1}, bytes(100)))
    with pytest.raises(ValueError, match='16 kHz'):
        bridge.capture(wire, tmp_path/'wrong.wav', 1)


def test_brief_playback_tail_does_not_end_followup_early(tmp_path):
    blocks = iter([b'\xd0\x07' * 1600] + [bytes(3200)] * 4)
    sent = []
    wire = SimpleNamespace(next_event=lambda: ('audio-chunk', {'rate': 16000, 'width': 2, 'channels': 1}, next(blocks)),
                           send=lambda *args: sent.append(args))
    assert not bridge.capture(wire, tmp_path / 'noise.wav', .5)
    assert sent == [('error', {'code': 'stt-no-text-recognized'})]


def test_announcement_plays_without_wake_then_listens(tmp_path, monkeypatch):
    client, satellite = socket.socketpair()
    client.settimeout(2)
    satellite.settimeout(2)
    controller, peer = bridge.Wire(client), bridge.Wire(satellite)
    announcements = bridge.Announcements()
    events, failures = [], []
    monkeypatch.setattr(bridge, 'voice_event', lambda name, **kw: events.append(name))
    def echo():
        try:
            assert peer.next_event()[0] == 'describe'
            peer.send('info', {'satellite': {'supports_jarvis_followup': True}})
            assert peer.next_event()[0] == 'run-satellite'
            # Arrives while the controller waits for a wake, not before startup.
            assert announcements.handle({'message': 'Welcome home.'})['queued']
            assert peer.next_event()[0] == 'audio-start'
            received = 0
            while True:
                kind, data, pcm = peer.next_event()
                received += len(pcm)
                if kind == 'audio-stop':
                    assert data['jarvis_followup'] == 1
                    assert received > 0
                    peer.send('played')
                    peer.send('run-pipeline', {'start_stage': 'asr'})
                    break
        except BaseException as exc:
            failures.append(exc)
        finally:
            peer.close()
    def synthesize(text, path):
        assert text == 'Welcome home.'
        with wave.open(path, 'wb') as output:
            output.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
            output.writeframes(bytes(4410))
        return path
    worker = threading.Thread(target=echo, daemon=True)
    worker.start()
    try:
        with pytest.raises(EOFError):
            bridge.serve(controller, None, None, synthesize, tmp_path, announcements=announcements)
        worker.join(3)
        assert not worker.is_alive()
        assert not failures
        assert 'command_server_instruction_finished' in events
        assert 'hassmic_listen_started' in events
        assert announcements.pending.empty()
    finally:
        controller.close()


def test_announcement_validation_and_bounded_queue():
    announcements = bridge.Announcements()
    assert not announcements.handle({'command': 'delete', 'text': 'x'})['ok']
    assert not announcements.handle({'text': ''})['ok']
    for _ in range(64):
        assert announcements.handle({'action': 'say', 'instruction': 'hello'})['queued']
    assert not announcements.handle({'text': 'overflow'})['ok']
    status = announcements.handle({'command': 'status'})
    assert status['pending_announcements'] == 64
    assert status['echo_connected'] is False


def test_reconnect_preserves_pending_announcements(tmp_path):
    announcements = bridge.Announcements()
    announcements.handle({'text': 'hello'})
    attempts = []
    class Finished(Exception):
        pass
    def connect(address, timeout):
        attempts.append(address)
        raise ConnectionRefusedError('test disconnected')
    def wait(seconds):
        assert seconds == 5
        if len(attempts) == 2:
            raise Finished
    with pytest.raises(Finished):
        bridge.run_connected('echo', 16700, None, None, None, tmp_path,
                             announcements, connect=connect, wait=wait)
    assert attempts == [('echo', 16700), ('echo', 16700)]
    assert announcements.pending.get_nowait() == 'hello'
    assert announcements.connected is False


@pytest.mark.parametrize('error', [EOFError('disconnected'), __import__('subprocess').CalledProcessError(1, 'piper')])
def test_reconnect_after_session_failure(tmp_path, monkeypatch, error):
    announcements = bridge.Announcements()
    closed = []
    attempts = []
    class Finished(BaseException):
        pass
    class FakeWire:
        def __init__(self, sock):
            pass
        def close(self):
            closed.append(True)
    def serve(*args, **kwargs):
        attempts.append(True)
        announcements.connected = True
        if len(attempts) == 1:
            raise error
        raise Finished
    monkeypatch.setattr(bridge, 'Wire', FakeWire)
    monkeypatch.setattr(bridge, 'serve', serve)
    with pytest.raises(Finished):
        bridge.run_connected('echo', 16700, None, None, None, tmp_path,
                             announcements, connect=lambda *a, **kw: object(), wait=lambda _: None)
    assert len(attempts) == 2
    assert closed == [True, True]
    assert announcements.connected is False


def test_wake_listening_logged_again_after_silence(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(bridge, 'voice_event', lambda name, **kw: events.append(name))
    monkeypatch.setattr(bridge, 'capture', lambda *a, **kw: False)
    incoming = iter([('info', {'satellite': {'supports_jarvis_followup': True}}, b''),
                     ('run-pipeline', {'start_stage': 'asr'}, b'')])
    def next_event():
        try:
            return next(incoming)
        except StopIteration:
            raise EOFError
    wire = SimpleNamespace(send=lambda *a: None, next_event=next_event,
                           sock=SimpleNamespace(settimeout=lambda _: None))
    with pytest.raises(EOFError):
        bridge.serve(wire, None, None, None, tmp_path)
    assert events.count('wake_heard') == 1
    assert events.count('wake_listen_started') == 2


@pytest.mark.parametrize('text', ['Computer, do setup.', 'do set up.', 'do set up do set up'])
def test_setup_command_is_local_and_never_sent_to_agent(tmp_path, monkeypatch, text):
    import voice_setup
    calls = []
    incoming = iter([('info', {'satellite': {'supports_jarvis_followup': True}}, b''),
                     ('run-pipeline', {'start_stage':'asr'}, b'')])
    wire = SimpleNamespace(send=lambda *a: None, next_event=lambda: next(incoming),
                           sock=SimpleNamespace(settimeout=lambda _: None))
    monkeypatch.setattr(bridge, 'capture', lambda *a, **kw: True)
    def setup(*args):
        calls.append('setup')
        raise EOFError('end test')
    monkeypatch.setattr(voice_setup, 'run_setup', setup)
    with pytest.raises(EOFError):
        bridge.serve(wire, lambda _: text,
                     lambda _: pytest.fail('setup sent to remote agent'), None, tmp_path)
    assert calls == ['setup']


def test_loaded_models_log_loader_fingerprints(monkeypatch):
    events = []
    monkeypatch.setattr(bridge, 'voice_event', lambda event, **kw: events.append((event, kw)))
    models = [{'slot': slot, 'name': name, 'sha256': str(slot)*64,
               'cutoff': .9, 'window': 5} for slot, name in enumerate(['Hey Jarvis', 'Computer'])]
    bridge.log_loaded_wake_models({'satellite': {'loaded_wake_models': models,
                                                'active_wake_words': ['alexa']}})
    assert [e[1]['name'] for e in events] == ['Hey Jarvis', 'Computer']
    assert all(e[0] == 'wake_model_loaded' for e in events)
    assert events[1][1]['sha256'] == '1'*64


@pytest.mark.parametrize('models', [None, [], 'computer', [{}],
    [{'slot': 0, 'name': 'Computer', 'sha256': 'bad', 'cutoff': .9, 'window': 5}]])
def test_missing_or_invalid_loader_evidence_never_claims_loaded(monkeypatch, models):
    events = []
    monkeypatch.setattr(bridge, 'voice_event', lambda name, **kw: events.append(name))
    bridge.log_loaded_wake_models({'satellite': {'loaded_wake_models': models}})
    assert events == ['wake_models_unverified']


def test_tcp_keepalive_detects_idle_satellite_loss():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    wire = bridge.Wire(sock)
    try:
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
        for name, expected in [('TCP_KEEPIDLE', 15), ('TCP_KEEPINTVL', 5),
                               ('TCP_KEEPCNT', 3)]:
            if hasattr(socket, name):
                assert sock.getsockopt(socket.IPPROTO_TCP, getattr(socket, name)) == expected
    finally:
        wire.close()


def test_tcp_keepalive_without_platform_tuning_options(monkeypatch):
    for name in ('TCP_KEEPIDLE', 'TCP_KEEPINTVL', 'TCP_KEEPCNT'):
        monkeypatch.delattr(socket, name, raising=False)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    wire = bridge.Wire(sock)
    try:
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE)
    finally:
        wire.close()


def test_no_speech_wait_expires_at_five_seconds(tmp_path):
    chunks = []
    def next_event():
        chunks.append(1)
        return ('audio-chunk', {'rate':16000,'width':2,'channels':1}, bytes(3200))
    sent = []
    wire = SimpleNamespace(next_event=next_event, send=lambda *args:sent.append(args))
    assert not bridge.capture(wire,tmp_path/'silence.wav',25,no_speech_seconds=5)
    assert 50 <= len(chunks) <= 51
    assert sent == [('error', {'code':'stt-no-text-recognized'})]


def test_speech_started_before_timeout_can_continue_past_five_seconds(tmp_path):
    chunks = [bytes(3200)]*40 + [b'\xd0\x07'*1600]*30 + [bytes(3200)]*20
    read = []
    def next_event():
        read.append(1)
        return ('audio-chunk', {'rate':16000,'width':2,'channels':1},chunks.pop(0))
    sent = []
    wire = SimpleNamespace(next_event=next_event,send=lambda *args:sent.append(args))
    path=tmp_path/'speech.wav'
    assert bridge.capture(wire,path,25,no_speech_seconds=5,silence=1.5)
    assert 85 <= len(read) <= 86
    assert sent == [('transcript', {'text':''})]
    with wave.open(str(path)) as audio:
        assert audio.getnframes()/16000 > 8
