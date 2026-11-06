"""Local reply rotation and arrival-prepared briefings; no work at import time."""
import json
import random
import re
import threading
import time
import uuid
from pathlib import Path

from config import (QUICK_REPLIES_ENABLED, QUICK_REPLIES_PATH, RESPONSE_CACHE_DIR,
                    BRIEFING_NEWS_TTL, BRIEFING_WEATHER_TTL, BRIEFING_PREPARE_COOLDOWN)
from voice_log import voice_event


def normalize(text):
    return ' '.join(re.sub(r"[^\w\s]", ' ', text.lower()).split())


class ResponseCache:
    def __init__(self, library=QUICK_REPLIES_PATH, directory=RESPONSE_CACHE_DIR,
                 enabled=QUICK_REPLIES_ENABLED, clock=time.time):
        self.library = Path(library)
        self.directory = Path(directory)
        self.enabled = enabled
        self.clock = clock
        self.lock = threading.RLock()
        self.library_stamp = None
        self.groups = {}
        self.last = {}
        self.refreshing = False
        self.worker = None
        self.versions = {}

    def reload(self):
        with self.lock:
            try:
                stamp = self.library.stat().st_mtime_ns
                if stamp == self.library_stamp:
                    return
                groups = json.loads(self.library.read_text(encoding='utf-8'))
                if not isinstance(groups, dict) or not groups:
                    raise ValueError('Expected reply groups')
                for group in groups.values():
                    for key in ('phrases', 'replies'):
                        values = group[key]
                        if not isinstance(values, list) or not values or any(
                                not isinstance(x, str) or not x.strip() or len(x) > 1000 for x in values):
                            raise ValueError('Expected nonempty bounded phrases/replies')
                self.groups, self.library_stamp = groups, stamp
            except (OSError, ValueError, KeyError, TypeError) as exc:
                voice_event('quick_replies_reload_failed', error=exc)

    def phrases(self):
        self.reload()
        with self.lock:
            return {normalize(p): name for name, group in self.groups.items() for p in group['phrases']}

    def hold_partial(self, text):
        if not self.enabled:
            return False
        text = normalize(text)
        phrases = list(self.phrases()) + list(BRIEFING_PHRASES) + list(REFRESH_PHRASES)
        return bool(text) and any(p == text or p.startswith(text + ' ') for p in phrases)

    def lookup(self, text):
        if not self.enabled:
            return None
        phrase = normalize(text)
        if phrase in REFRESH_PHRASES:
            return None
        name = self.phrases().get(phrase)
        if name:
            with self.lock:
                replies = self.groups[name]['replies']
                choices = [r for r in replies if r != self.last.get(name)] or replies
                reply = random.choice(choices)
                self.last[name] = reply
            return {'reply': reply, 'source': name}
        topic = BRIEFING_PHRASES.get(phrase)
        if topic:
            try:
                item = json.loads((self.directory / f'{topic}.json').read_text())
                age = self.clock() - item['created']
                ttl = BRIEFING_NEWS_TTL if topic == 'news' else BRIEFING_WEATHER_TTL
                if (0 <= age < ttl and isinstance(item.get('reply'), str)
                        and item['reply'].strip() and len(item['reply']) <= 3000):
                    return {'reply': item['reply'], 'source': topic}
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return None

    def refresh(self, topic, fetch=None):
        """Explicit refresh bypasses TTL/cooldown; newest request owns the cache."""
        with self.lock:
            version = self.versions.get(topic, 0) + 1
            self.versions[topic] = version
        reply = (fetch or fetch_briefing)(topic, BRIEFING_PROMPTS[topic])
        if not isinstance(reply, str) or not reply.strip() or len(reply) > 3000:
            raise ValueError('Invalid briefing')
        with self.lock:
            if self.versions[topic] == version:
                try:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    path = self.directory / f'{topic}.json'
                    temp = path.with_suffix('.tmp')
                    temp.write_text(json.dumps({'created': self.clock(), 'reply': reply}), encoding='utf-8')
                    temp.replace(path)
                except OSError as exc:
                    # A storage failure must not hide a successful fresh answer.
                    voice_event('briefing_store_failed', topic=topic, error=exc)
        return {'reply': reply, 'source': f'{topic}_refresh'}

    def prepare(self, fetch=None, *, briefings=True):
        """Coalesce simultaneous arrival triggers; never speak or block the HTTP caller."""
        if not self.enabled:
            return {'ok': False, 'error': 'Quick responses are disabled'}
        with self.lock:
            if self.refreshing:
                return {'ok': True, 'queued': False, 'preparing': True}
            if briefings:
                marker = self.directory / 'last_preparation.json'
                try:
                    last = json.loads(marker.read_text())['started']
                    age = self.clock() - last
                    if 0 <= age < BRIEFING_PREPARE_COOLDOWN:
                        return {'ok': True, 'queued': False, 'reason': 'cooldown',
                                'retry_after_seconds': int(BRIEFING_PREPARE_COOLDOWN - age)}
                except (OSError, ValueError, TypeError, KeyError):
                    pass
                try:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    temp = marker.with_suffix('.tmp')
                    temp.write_text(json.dumps({'started': self.clock()}), encoding='utf-8')
                    temp.replace(marker)
                except OSError as exc:
                    voice_event('briefing_prepare_failed', error=exc)
                    return {'ok': False, 'error': 'Cannot persist preparation cooldown'}
            self.refreshing = True
        def work():
            try:
                if briefings:
                    for topic, prompt in BRIEFING_PROMPTS.items():
                        try:
                            self.refresh(topic, fetch)
                            voice_event('briefing_prepared', topic=topic)
                        except Exception as exc:
                            voice_event('briefing_prepare_failed', topic=topic, error=exc)
                self.reload()
            except Exception as exc:
                voice_event('quick_replies_prepare_failed', error=exc)
            finally:
                with self.lock:
                    self.refreshing = False
        self.worker = threading.Thread(target=work, name='response-cache', daemon=True)
        self.worker.start()
        return {'ok': True, 'queued': True}


BRIEFING_PHRASES = {normalize(p): topic for topic, phrases in {
    'news': ["what's the news", "what's the latest news", 'tell me the news', 'latest news',
             'news', 'give me the headlines', 'what are the headlines', 'how s the morning news'],
    'weather': ["what's the weather", "what's the weather today", 'how is the weather',
                "how's the weather outside", 'weather', 'tell me the weather'],
}.items() for p in phrases}
REFRESH_PHRASES = {normalize(phrase): topic for topic in ('news', 'weather')
                   for phrase in (f'update {topic}', f'update the {topic}',
                                  f'refresh {topic}', f'refresh the {topic}')}
BRIEFING_PROMPTS = {
    'news': 'Prepare a short spoken briefing of the top three current news headlines. '
            'Use current sources. Include the date and three concise headlines. '
            'No greeting, questions, links, or home actions. If current news cannot be verified, say so.',
    'weather': 'Prepare a short spoken current local weather briefing for the configured household location. '
               'Use current weather data. Include location, conditions, temperature, and today’s forecast. '
               'No greeting, questions, links, or home actions. Do not guess the location or weather.',
}


def fetch_briefing(topic, prompt):
    from call_agent_api import post_pasture_message, parse_agent_reply
    content = post_pasture_message(prompt, conversation_id=f'jarvis-prepared-{topic}-{uuid.uuid4().hex}',
                                   log_label='briefing', timeout=60)
    return parse_agent_reply(content)['reply']


cache = ResponseCache()


def local_reply(text):
    topic = REFRESH_PHRASES.get(normalize(text)) if cache.enabled else None
    if topic:
        try:
            voice_event('briefing_refresh_requested', topic=topic)
            return cache.refresh(topic)
        except Exception as exc:
            voice_event('briefing_refresh_failed', topic=topic, error=exc)
            return {'reply': f"I couldn’t update the {topic} right now. Please try again.",
                    'source': f'{topic}_refresh_failed'}
    try:
        result = cache.lookup(text)
        if result:
            voice_event('local_reply', source=result['source'], text=result['reply'])
        return result
    except Exception as exc:
        voice_event('local_reply_failed', error=exc)
        return None


def handle_cache_command(payload):
    command = str(payload.get('command') or payload.get('action') or '').replace('_', ' ').strip().lower()
    if command not in {'prepare briefings', 'reload quick replies'}:
        return None
    return cache.prepare(briefings=command == 'prepare briefings')
