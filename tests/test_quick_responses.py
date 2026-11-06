import json
import threading
from pathlib import Path

import pytest
import quick_responses as qr


@pytest.fixture
def cache(tmp_path):
    library = tmp_path / 'replies.json'
    library.write_text(json.dumps({'checkin': {'phrases': ['how are you'], 'replies': ['Well.', 'Great.']}}))
    return qr.ResponseCache(library, tmp_path / 'cache', enabled=True, clock=lambda: 1000)


def test_rotation_cache_and_compound_request(cache):
    first = cache.lookup('How are you?')
    second = cache.lookup('how are you')
    assert first['reply'] != second['reply']
    assert cache.lookup('how are you and what is the news') is None
    assert cache.lookup('how are you')
    assert not cache.directory.exists()
    assert 'path' not in first


def test_reload_preserves_last_good_library(cache):
    assert cache.lookup('how are you')
    cache.library.write_text('{broken')
    assert cache.lookup('how are you')
    cache.library.write_text(json.dumps({'joke': {'phrases': ['tell me a joke'], 'replies': ['Funny.']}}))
    assert cache.lookup('tell me a joke')['reply'] == 'Funny.'
    assert cache.lookup('how are you') is None


def test_partial_candidates(cache):
    for phrase in ['how', 'how are', 'how are you', 'what s the latest news']:
        assert cache.hold_partial(phrase)
    assert not cache.hold_partial('how are you and what is the time')
    cache.enabled = False
    assert not cache.hold_partial('how are you')


def test_prepare_atomic_expiry_and_failure(cache):
    assert cache.prepare(lambda topic, prompt: f'{topic} briefing')['ok']
    cache.worker.join(3)
    assert not cache.worker.is_alive()
    assert cache.lookup('what s the latest news')['reply'] == 'news briefing'
    assert cache.lookup('what s the weather')['reply'] == 'weather briefing'
    cache.clock = lambda: 1000 + qr.BRIEFING_WEATHER_TTL
    assert cache.lookup('weather') is None
    assert cache.lookup('news')
    cache.clock = lambda: 1000 + qr.BRIEFING_NEWS_TTL
    assert cache.lookup('news') is None
    def failed(*args):
        raise RuntimeError('offline')
    cache.prepare(failed)
    cache.worker.join(3)
    assert not cache.refreshing
    assert cache.lookup('news') is None


def test_prepare_coalesces_and_does_not_block(cache):
    gate = threading.Event()
    def fetch(topic, prompt):
        gate.wait(2)
        return 'Briefing.'
    assert cache.prepare(fetch)['queued']
    assert not cache.prepare(fetch)['queued']
    gate.set()
    cache.worker.join(3)


def test_library_has_fifty_distinct_jokes():
    library = json.loads(Path(qr.QUICK_REPLIES_PATH).read_text())
    assert len(set(library['joke']['replies'])) == 50


def test_streaming_input_holds_quick_request(cache, monkeypatch):
    from streaming_input import StreamingInput
    monkeypatch.setattr(qr, 'cache', cache)
    with StreamingInput() as upstream:
        upstream.partial('how are you')
        assert upstream.thread is None


def test_command_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(qr.cache, 'prepare', lambda **kw: calls.append(kw) or {'ok': True})
    assert qr.handle_cache_command({'command': 'prepare_briefings'}) == {'ok': True}
    assert qr.handle_cache_command({'command': 'reload_quick_replies'}) == {'ok': True}
    assert calls == [{'briefings': True}, {'briefings': False}]
    assert qr.handle_cache_command({'command': 'speak'}) is None


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('request_text', ['how are you', 'update news', 'update weather'])
def test_echo_local_reply_current_voice_and_followup(cache, monkeypatch, tmp_path, streaming, request_text):
    from types import SimpleNamespace
    import hassmic_jarvis as bridge
    import streaming_reply
    import streaming_stt
    monkeypatch.setattr(qr, 'cache', cache)
    monkeypatch.setattr(qr, 'fetch_briefing', lambda *_: 'Fresh briefing.')
    texts = iter([request_text, 'tell me more'])
    events = iter([('info', {'satellite': {'supports_jarvis_followup': True}}, b''),
                   ('run-pipeline', {'start_stage': 'asr'}, b''),
                   ('run-pipeline', {'start_stage': 'asr'}, b'')])
    wire = SimpleNamespace(send=lambda *a, **k: None, next_event=lambda: next(events),
                           sock=SimpleNamespace(settimeout=lambda _: None))
    monkeypatch.setattr(bridge, 'capture', lambda *a, **k: True)
    monkeypatch.setattr(bridge, 'STREAMING_INPUT_ENABLED', True)
    class Incremental:
        def __init__(self, *a, **kw):
            self.partial = kw.get('on_partial')
        def finish(self):
            text = next(texts)
            if self.partial:
                self.partial(text)
            return text
        def close(self):
            pass
    monkeypatch.setattr(streaming_stt, 'IncrementalTranscript', Incremental)
    spoken, played, requests = [], [], []
    def synthesize(text, path):
        spoken.append(text)
        return path
    monkeypatch.setattr(bridge, 'play', lambda wire, path, **kw: played.append(kw))
    def ask(text):
        requests.append(text)
        return {'reply': 'More detail.'}
    monkeypatch.setattr(streaming_reply, 'stream_reply', lambda wire, text, *a, **kw: ask(text))
    bridge.serve(wire, lambda _: next(texts), ask, synthesize, tmp_path, max_turns=2,
                 streaming_server=SimpleNamespace(transcribe=lambda _: '') if streaming else None)
    assert spoken[0] in ['Well.', 'Great.', 'Fresh briefing.']
    assert played[0] == {'followup': True}
    assert len(requests) == 1
    assert spoken[0] in requests[0]
    assert 'Current user request: tell me more' in requests[0]
    assert not list(cache.directory.glob('*.wav'))


@pytest.mark.parametrize('platform', ['linux', 'win32'])
def test_native_reply_uses_existing_speech_path(cache, monkeypatch, platform):
    import conversation_loop as loop
    import sys
    monkeypatch.setattr(sys, 'platform', platform)
    monkeypatch.setattr(qr, 'cache', cache)
    spoken = []
    monkeypatch.setattr(loop, 'speak', lambda text, **kw: spoken.append(text))
    monkeypatch.setattr(loop, 'ask_pasture', lambda *_: pytest.fail('No backend for quick replies'))
    token = loop._local_reply_context.set(None)
    try:
        assert loop.ask_and_speak('how are you', None)
        assert spoken[0] in ['Well.', 'Great.']
        assert loop._local_reply_context.get()[1] == spoken[0]
    finally:
        loop._local_reply_context.reset(token)


def test_briefing_uses_existing_backend(monkeypatch):
    import call_agent_api
    calls = []
    monkeypatch.setattr(call_agent_api, 'post_pasture_message',
                        lambda text, **kw: calls.append((text, kw)) or '{"reply":"Today’s news."}')
    assert qr.fetch_briefing('news', 'news request') == 'Today’s news.'
    assert calls[0][0] == 'news request'
    assert calls[0][1]['conversation_id'].startswith('jarvis-prepared-news-')


def test_config_overrides_in_fresh_process(tmp_path):
    import os
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if not k.startswith('JARVIS_')}
    env.update(JARVIS_QUICK_REPLIES_ENABLED='true', JARVIS_BRIEFING_NEWS_TTL='120',
               JARVIS_BRIEFING_WEATHER_TTL='60', JARVIS_RESPONSE_CACHE_DIR=str(tmp_path))
    result = subprocess.run([sys.executable, '-c',
        'import config; print(config.QUICK_REPLIES_ENABLED, config.BRIEFING_NEWS_TTL, config.BRIEFING_WEATHER_TTL)'],
        env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'True 120 60'
    env['JARVIS_BRIEFING_WEATHER_TTL'] = '0'
    result = subprocess.run([sys.executable, '-c', 'import config'], env=env, capture_output=True, text=True)
    assert result.returncode != 0 and 'must be positive' in result.stderr


def test_arrival_cooldown_shared_persisted_and_expires(cache):
    calls = []
    def fetch(topic, prompt):
        calls.append(topic)
        return 'Prepared text.'
    cache.prepare(fetch)
    cache.worker.join(3)
    assert calls == ['news', 'weather']
    assert cache.prepare(fetch)['reason'] == 'cooldown'
    restarted = qr.ResponseCache(cache.library, cache.directory, enabled=True, clock=lambda: 1100)
    assert restarted.prepare(fetch)['reason'] == 'cooldown'
    # Library reload does not call the backend or reset the arrival cooldown.
    restarted.prepare(fetch, briefings=False)
    restarted.worker.join(3)
    assert calls == ['news', 'weather']
    restarted.clock = lambda: 1000 + qr.BRIEFING_PREPARE_COOLDOWN
    assert restarted.prepare(fetch)['queued']
    restarted.worker.join(3)
    assert calls == ['news', 'weather', 'news', 'weather']


@pytest.mark.parametrize('topic', ['news', 'weather'])
def test_explicit_refresh_bypasses_cache_and_arrival_cooldown(cache, monkeypatch, topic):
    monkeypatch.setattr(qr, 'cache', cache)
    cache.prepare(lambda *_: 'Old briefing.')
    cache.worker.join(3)
    marker = (cache.directory / 'last_preparation.json').read_text()
    calls = []
    monkeypatch.setattr(qr, 'fetch_briefing', lambda name, prompt: calls.append(name) or 'Fresh briefing.')
    reply = qr.local_reply(f'Update {topic}!')
    assert reply['reply'] == 'Fresh briefing.'
    assert calls == [topic]
    assert cache.lookup(topic)['reply'] == 'Fresh briefing.'
    assert (cache.directory / 'last_preparation.json').read_text() == marker
    assert cache.lookup('weather' if topic == 'news' else 'news')['reply'] == 'Old briefing.'
    qr.local_reply(f'update {topic}')
    assert calls == [topic, topic]
    assert cache.hold_partial('update') and cache.hold_partial(f'update {topic}')
    assert not cache.hold_partial(f'update {topic} and turn off the lights')


def test_failed_explicit_refresh_never_serves_cached_answer(cache, monkeypatch):
    monkeypatch.setattr(qr, 'cache', cache)
    cache.refresh('news', lambda *_: 'Old briefing.')
    def fail(*_):
        raise RuntimeError('offline')
    monkeypatch.setattr(qr, 'fetch_briefing', fail)
    result = qr.local_reply('update news')
    assert result['source'] == 'news_refresh_failed'
    assert 'Old briefing.' not in result['reply']
    assert cache.lookup('news')['reply'] == 'Old briefing.'


def test_arrival_cannot_overwrite_newer_manual_refresh(cache):
    entered, release = threading.Event(), threading.Event()
    def slow(*_):
        entered.set()
        assert release.wait(3)
        return 'Older arrival answer.'
    thread = threading.Thread(target=lambda: cache.refresh('news', slow))
    thread.start()
    assert entered.wait(3)
    try:
        cache.refresh('news', lambda *_: 'New manual answer.')
    finally:
        release.set()
        thread.join(3)
    assert cache.lookup('news')['reply'] == 'New manual answer.'
