import io
import json
import threading
import wave
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

import streaming_reply as reply
from streaming_stt import IncrementalTranscript, wav_bytes


def test_final_transcript_never_uses_stale_draft():
    entered, release = threading.Event(), threading.Event()
    seen = []
    def transcribe(pcm):
        seen.append(pcm)
        if len(seen) == 1:
            entered.set()
            assert release.wait(2)
            return 'turn on kitchen lights'
        return 'turn on living room lights'
    session = IncrementalTranscript(transcribe)
    try:
        first = b'\x01\x00' * 16000
        session.update([first[:5120]], .16, .16)
        session.update([first], 1, 1)
        assert entered.wait(2)
        session.update([first, b'\x02\x00'*16000], 2, 2)
        assert len(seen) == 1  # no queue of stale snapshots
        release.set()
        assert session.finish() == 'turn on living room lights'
        assert len(seen) == 2
        assert b'\x02\x00' in seen[1]
    finally:
        release.set()
        session.close()


def test_silence_has_no_transcription_and_current_snapshot_is_reused():
    calls = []
    s = IncrementalTranscript(lambda pcm: calls.append(pcm) or 'hello')
    try:
        s.update([bytes(32000)], None, 1)
        assert s.finish() == ''
        assert not calls
        s.update([b'\x01\x00'*16000], 1, 1)
        assert s.finish() == 'hello'
        s.update([b'\x01\x00'*16000, bytes(32000)], 1, 2)
        assert s.finish() == 'hello'
        s.update([b'\x01\x00'*16000, bytes(64000)], 1, 3)
        assert s.finish() == 'hello'
        assert len(calls) == 2  # real trailing audio retained, later silence reused
    finally:
        s.close()


def test_wav_snapshot_format():
    with wave.open(io.BytesIO(wav_bytes(bytes(3200)))) as w:
        assert (w.getframerate(), w.getsampwidth(), w.getnchannels(), w.getnframes()) == (16000, 2, 1, 1600)


def fake_tts(text, path):
    with wave.open(path, 'wb') as w:
        w.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
        w.writeframes(bytes(440))
    return path


def test_drafts_never_play_and_only_committed_text_is_spoken(tmp_path, monkeypatch):
    sent, synthesized = [], []
    monkeypatch.setattr(reply, 'voice_event', lambda *a, **k: None)
    wire = SimpleNamespace(send=lambda *a, **k: sent.append((a,k)),
                           next_event=lambda: ('played', {}, b''))
    def synth(text, path):
        synthesized.append(text)
        return fake_tts(text, path)
    def events(_):
        yield {'type': 'draft_reset'}
        yield {'type': 'draft_delta', 'text': 'The kitchen lights are on. '}
        assert not sent
        yield {'type': 'progress', 'message': 'internal progress'}
        assert not sent
        yield {'type': 'reply', 'content': 'The living room lights are on. Anything else?'}
        yield {'type': 'done'}
    reply.stream_reply(wire, 'request', synth, tmp_path, events=events)
    assert 'The living room lights are on.' in synthesized
    assert 'Anything else?' in synthesized
    assert sum(a[0] == 'audio-start' for a, _ in sent) == 1
    assert sum(a[0] == 'audio-stop' for a, _ in sent) == 1
    assert sent[-1][0] == ('audio-stop', {'jarvis_followup': 1})


def test_broken_draft_never_reaches_speaker(tmp_path):
    def events(_):
        yield {'type': 'draft_delta', 'text': 'Unconfirmed answer. '}
        raise EOFError('lost connection')
    wire = SimpleNamespace(send=lambda *a, **k: pytest.fail('played an uncommitted draft'))
    with pytest.raises(EOFError):
        reply.stream_reply(wire, 'test', fake_tts, tmp_path, events=events)


@pytest.mark.parametrize('trailer,valid', [('', False), ('event: done\ndata: {}\n\n', True)])
def test_sse_utf8_and_required_completion(monkeypatch, trailer, valid):
    content = 'event: reply\ndata: '+json.dumps({'content': 'It’s 60°F.'}, ensure_ascii=False)+'\n\n'+trailer
    class Response:
        headers = {'Content-Type': 'text/event-stream'}
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def raise_for_status(self): pass
        def iter_lines(self, **kw): return iter(content.encode().split(b'\n'))
    calls = []
    monkeypatch.setattr(reply.requests, 'post', lambda *a, **kw: calls.append(kw) or Response())
    if valid:
        assert list(reply.api_events('hello'))[0]['content'] == 'It’s 60°F.'
    else:
        with pytest.raises(EOFError): list(reply.api_events('hello'))
    assert len(calls) == 1
    assert calls[0]['json']['stream'] is True


def test_old_json_api_uses_same_request(monkeypatch):
    class Response:
        headers = {'Content-Type': 'application/json'}
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':{'content':'Hello.'}}]}
    calls = []
    monkeypatch.setattr(reply.requests, 'post', lambda *a, **kw: calls.append(kw) or Response())
    assert list(reply.api_events('hi')) == [{'type':'reply','content':'Hello.'},{'type':'done'}]
    assert len(calls) == 1


def test_sentence_boundaries_and_json_reply():
    assert reply.sentences('Dr. Smith says it is 61.5 degrees. Part') == (['Dr. Smith says it is 61.5 degrees.'], 'Part')
    assert reply.speech_text('{"reply":"Hello!","continue_listening":true}') == 'Hello!'


@pytest.mark.parametrize('value,valid', [('4', True), ('0', False), ('33', False)])
def test_streaming_config_in_fresh_process(value, valid):
    result = subprocess.run([sys.executable, '-c', 'import config; print(config.STREAMING_WHISPER_THREADS)'],
                            env=dict(os.environ, JARVIS_STREAMING_WHISPER_THREADS=value),
                            capture_output=True, text=True)
    assert (result.returncode == 0) == valid


@pytest.mark.parametrize('name', ['whisper-cli', 'whisper-cli.exe'])
def test_managed_server_binary_and_shutdown(tmp_path, monkeypatch, name):
    import streaming_stt as stt
    binary = tmp_path / name
    server_path = tmp_path / ('whisper-server.exe' if name.endswith('.exe') else 'whisper-server')
    server_path.write_bytes(b'fake executable')
    monkeypatch.setattr(stt, 'WHISPER_CPP_BINARY', str(binary))
    monkeypatch.setattr(stt, 'LOG_DIR', str(tmp_path))
    class Probe:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def bind(self,address): assert address == ('127.0.0.1',0)
        def getsockname(self): return ('127.0.0.1',12345)
    monkeypatch.setattr(stt.socket, 'socket', Probe)
    calls=[]
    process=SimpleNamespace(poll=lambda:None,terminate=lambda:calls.append('terminated'),wait=lambda *a:0)
    def popen(args, **kwargs):
        assert args[0]==str(server_path)
        assert args[args.index('--host')+1]=='127.0.0.1'
        return process
    monkeypatch.setattr(stt.subprocess,'Popen',popen)
    monkeypatch.setattr(stt,'urlopen',lambda *a,**k:io.BytesIO(b'{"status":"ok"}'))
    server=stt.WhisperServer().start()
    server.close()
    assert calls==['terminated']
