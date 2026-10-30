import json
import threading
from types import SimpleNamespace

import pytest

import streaming_input as upstream
import streaming_reply
from streaming_stt import IncrementalTranscript


class Response:
    headers = {'Content-Type': 'text/event-stream'}
    def close(self): pass
    def raise_for_status(self): pass
    def iter_lines(self, **kw):
        return iter(['event: reply', 'data: {"content":"Final answer."}', '',
                     'event: done', 'data: {}', ''])


@pytest.mark.parametrize('text', ['cancel', 'cancel stop', 'quiet', 'stand', 'stand down',
                                 'Computer, stop listening please'])
def test_local_control_partials_do_not_open_api_request(monkeypatch, text):
    monkeypatch.setattr(upstream.requests, 'post', lambda *a, **k: pytest.fail('Local control opened API'))
    with upstream.StreamingInput() as session:
        session.partial(text)
        assert session.thread is None
        assert session.pending is None


def test_cancel_timer_still_reaches_backend(monkeypatch):
    sent = threading.Event()
    def post(*args, **kwargs):
        for chunk in kwargs['data']:
            event = json.loads(chunk)
            if event.get('text') == 'cancel the timer':
                sent.set()
        return Response()
    monkeypatch.setattr(upstream.requests, 'post', post)
    with upstream.StreamingInput() as session:
        session.partial('cancel')
        assert session.thread is None
        session.partial('cancel the timer')
        assert sent.wait(2)


def test_upload_sends_partial_before_commit_and_only_one_final_request(monkeypatch):
    got_partial = threading.Event()
    records, calls = [], []
    def post(*args, **kwargs):
        calls.append(kwargs)
        for chunk in kwargs['data']:
            event = json.loads(chunk)
            records.append(event)
            if event['type'] == 'partial':
                got_partial.set()
        return Response()
    monkeypatch.setattr(upstream.requests, 'post', post)
    with upstream.StreamingInput() as session:
        session.partial('Turn on kitchen lights.')
        assert got_partial.wait(2)
        assert [e['type'] for e in records] == ['start', 'partial']
        assert records[-1]['text'] == 'turn on kitchen lights'
        events = list(session.events('turn off living room lights'))
        assert events[-1]['type'] == 'done'
    assert records[-1] == {'type': 'commit', 'text': 'turn off living room lights'}
    assert len(calls) == 1
    assert calls[0]['headers']['Content-Type'] == 'application/x-ndjson'


def test_close_cancels_partial_without_commit(monkeypatch):
    seen, partial = [], threading.Event()
    def post(*args, **kwargs):
        for chunk in kwargs['data']:
            seen.append(json.loads(chunk))
            if seen[-1]['type'] == 'partial': partial.set()
        return Response()
    monkeypatch.setattr(upstream.requests, 'post', post)
    with upstream.StreamingInput() as session:
        session.partial('turn on kitchen')
        assert partial.wait(2)
    assert seen[-1] == {'type': 'cancel'}
    assert not session.thread.is_alive()
    assert not any(e['type'] == 'commit' for e in seen)


def test_failed_committed_upload_never_replays(monkeypatch):
    partial = threading.Event()
    calls = []
    def post(*args, **kwargs):
        calls.append(kwargs)
        for chunk in kwargs['data']:
            if json.loads(chunk)['type'] == 'partial': partial.set()
        raise OSError('lost after commit')
    monkeypatch.setattr(upstream.requests, 'post', post)
    with upstream.StreamingInput() as session:
        session.partial('turn on light')
        assert partial.wait(2)
        with pytest.raises(OSError, match='lost after commit'):
            list(session.events('turn on light'))
    assert len(calls) == 1


def test_precommit_failure_can_fall_back_once(monkeypatch):
    monkeypatch.setattr(upstream.requests, 'post', lambda *a, **k: (_ for _ in ()).throw(OSError('offline')))
    calls = []
    monkeypatch.setattr(streaming_reply, 'api_events', lambda text: calls.append(text) or iter([{'type': 'done'}]))
    with upstream.StreamingInput() as session:
        session.partial('hello')
        assert session.ready.wait(2)
        assert list(session.events('hello')) == [{'type': 'done'}]
    assert calls == ['hello']


def test_incremental_publishes_ready_transcript_during_trailing_silence():
    partials = []
    s = IncrementalTranscript(lambda pcm: 'what is two plus two', on_partial=partials.append)
    try:
        frames = [b'\x01\x00' * 16000]
        s.update(frames[:], .16, .16)
        s.update(frames[:], 1, 1)
        s.future.result(timeout=2)
        s.update(frames + [bytes(9600)], 1, 1.3)
        assert partials == ['what is two plus two']
        s.future.result(timeout=2)
        s.update(frames + [bytes(16000)], 1, 1.5)
        assert len(partials) == 2
        s.update(frames + [bytes(32000)], 1, 2)
        assert len(partials) == 2  # never publish one future repeatedly
    finally:
        s.close()


@pytest.mark.parametrize('text', ['stop', 'stand down', 'do setup', ''])
def test_local_control_cancels_upstream(tmp_path, monkeypatch, text):
    import hassmic_jarvis as bridge
    import streaming_stt
    import conversation_loop
    import voice_setup
    import call_agent_api
    monkeypatch.setattr(conversation_loop, '_stand_down_until', 0)
    monkeypatch.setattr(bridge, 'STREAMING_INPUT_ENABLED', True)
    closed = []
    class Upload:
        def __enter__(self): return self
        def __exit__(self,*args): closed.append(True)
        def partial(self,text): pass
        def events(self,text): pytest.fail('local command committed to Pasture')
    monkeypatch.setattr(upstream, 'StreamingInput', Upload)
    monkeypatch.setattr(streaming_stt, 'IncrementalTranscript', lambda *a,**k:
        SimpleNamespace(finish=lambda:text,close=lambda:None))
    monkeypatch.setattr(bridge, 'capture', lambda *a, **k: True)
    monkeypatch.setattr(bridge, 'play', lambda *a, **k: None)
    monkeypatch.setattr(voice_setup, 'run_setup', lambda *a: None)
    monkeypatch.setattr(call_agent_api, 'start_new_pasture_session', lambda:None)
    def next_event():
        if responses:
            return responses.pop(0)
        raise EOFError('end fixture')
    responses = [('info', {'satellite':{'supports_jarvis_followup':True}}, b''),
                 ('run-pipeline', {'start_stage':'asr'}, b'')]
    wire = SimpleNamespace(send=lambda *a,**k:None, next_event=next_event,
        ready=lambda *a: (_ for _ in ()).throw(EOFError('end fixture')),
        sock=SimpleNamespace(settimeout=lambda t:None))
    with pytest.raises(EOFError):
        bridge.serve(wire,None,None,lambda *a:'unused.wav',tmp_path,
                     streaming_server=SimpleNamespace(transcribe=lambda x:''))
    assert closed == [True]
