"""Prepare draft speech early; play only the validated Pasture reply."""
import json
from contextvars import copy_context
from device_context import conversation_id as current_conversation_id, request_headers
import re
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from config import API_URL, API_MODEL, API_CONVERSATION_ID, MAX_TTS_CHARS, PIPER_SENTENCE_SILENCE
from call_agent_api import parse_agent_reply
from text_to_speech import clean_for_tts
from voice_log import voice_event


def api_events(text):
    """One request only. A broken stream must never retry a home action."""
    conversation_id = current_conversation_id()
    with requests.post(API_URL, headers={
        'Content-Type': 'application/json', 'Accept': 'text/event-stream',
        'X-Pasture-Conversation-Id': conversation_id, **request_headers(),
    }, json={'model': API_MODEL, 'conversation_id': conversation_id,
             'stream': True, 'messages': [{'role': 'user', 'content': text}]},
             stream=True, timeout=(5, 90)) as response:
        yield from response_events(response)


def response_events(response):
    """Shared decoder for final-only JSON requests and incremental uploads."""
    response.raise_for_status()
    if 'text/event-stream' not in response.headers.get('Content-Type', ''):
        # Old API servers remain usable; this is the same request, not a replay.
        content = response.json()['choices'][0]['message']['content']
        yield {'type': 'reply', 'content': content}
        yield {'type': 'done'}
        return
    event = 'message'
    data = []
    committed = False
    for line in response.iter_lines(chunk_size=1, decode_unicode=True):
        if isinstance(line, bytes):
            line = line.decode('utf-8')
        if line.startswith('event:'):
            event = line[6:].strip()
        elif line.startswith('data:'):
            data.append(line[5:].lstrip())
            if sum(map(len, data)) > 256_000:
                raise ValueError('Oversized Pasture event')
        elif not line and data:
            payload = json.loads('\n'.join(data))
            data = []
            if not isinstance(payload, dict):
                raise ValueError('Invalid Pasture event')
            payload['type'] = event
            event = 'message'
            if payload['type'] == 'error':
                raise RuntimeError(payload.get('message', 'Pasture stream failed'))
            if payload['type'] == 'reply':
                if committed:
                    raise ValueError('Duplicate Pasture reply')
                committed = True
            yield payload
            if payload['type'] == 'done':
                if not committed:
                    raise ValueError('Pasture finished without a reply')
                return
    raise EOFError('Pasture stream ended without completion')


def sentences(text, final=False):
    """Split speech at punctuation; keep the unfinished tail until more arrives."""
    parts = []
    start = 0
    for match in re.finditer(r'[.!?](?:["\u201d\u2019])?(?=\s)', text):
        end = match.end()
        # Avoid splitting common short abbreviations or decimals.
        word = text[start:end].split()[-1]
        if word.lower() in {'mr.', 'mrs.', 'ms.', 'dr.', 'st.', 'vs.', 'e.g.', 'i.e.'}:
            continue
        part = text[start:end].strip()
        if part:
            parts.append(part)
        start = end
    tail = text[start:].strip()
    if final and tail:
        parts.append(tail)
        tail = ''
    return parts, tail


def speech_text(content):
    return clean_for_tts(parse_agent_reply(content)['reply'])


class PreparedSpeech:
    def __init__(self, synthesize, directory):
        self.synthesize = synthesize
        self.directory = Path(directory)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='piper-stream')
        self.cache = {}
        self.next_file = 0

    def prepare(self, text, speculative=False):
        if text not in self.cache:
            # Draft work must not swamp final speech with an unbounded queue.
            if speculative and len(self.cache) >= 2:
                return None
            path = str(self.directory / f'stream-{self.next_file}.wav')
            self.next_file += 1
            self.cache[text] = self.pool.submit(copy_context().run, self.synthesize, text, path)
        return self.cache[text]

    def reset(self):
        for future in self.cache.values():
            future.cancel()
        self.cache.clear()

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)


def play_sentences(wire, parts, prepared, followup=True):
    futures = [prepared.prepare(part) for part in parts]
    audio_format = None
    for future in futures:
        path = future.result()
        with wave.open(str(path), 'rb') as audio:
            current = (audio.getframerate(), audio.getsampwidth(), audio.getnchannels())
            if current[1:] != (2, 1):
                raise ValueError('Expected mono 16-bit streaming reply')
            if audio_format is None:
                audio_format = current
                wire.send('audio-start', {'rate': current[0], 'width': 2, 'channels': 1})
                voice_event('streaming_first_audio_sent')
            elif current != audio_format:
                raise ValueError('Piper audio format changed during reply')
            else:
                silence = bytes(int(current[0] * PIPER_SENTENCE_SILENCE) * 2)
                for offset in range(0, len(silence), 2048):
                    wire.send('audio-chunk', payload=silence[offset:offset+2048])
            while pcm := audio.readframes(1024):
                wire.send('audio-chunk', payload=pcm)
    if audio_format is None:
        raise ValueError('No spoken reply')
    wire.send('audio-stop', {'jarvis_followup': int(followup)})
    while True:
        kind, _, _ = wire.next_event()
        if kind == 'played':
            return
        if kind == 'run-pipeline':
            raise RuntimeError('New wake interrupted streaming reply')


def stream_reply(wire, text, synthesize, directory, events=api_events, *, followup=True):
    started = time.monotonic()
    prepared = PreparedSpeech(synthesize, directory)
    draft = ''
    replied = False
    stream = events(text)
    try:
        for event in stream:
            kind = event.get('type')
            if kind == 'timing':
                voice_event('pasture_timing', stage=event.get('stage'), elapsed_ms=event.get('elapsedMs'),
                            provisional_match=event.get('provisionalMatch'))
            elif kind == 'draft_reset':
                draft = ''
                prepared.reset()
            elif kind == 'draft_delta':
                draft = (draft + str(event.get('text', '')))[:MAX_TTS_CHARS]
                # JSON envelopes and internal tags remain drafts until validated.
                if not draft.lstrip().startswith(('{', '[', '<', '`')):
                    parts, _ = sentences(draft)
                    for part in parts[:2]:
                        prepared.prepare(clean_for_tts(part), speculative=True)
            elif kind == 'reply':
                if replied:
                    raise ValueError('Multiple committed replies')
                content = speech_text(event['content'])
                parts, _ = sentences(content, final=True)
                voice_event('streaming_reply_committed', elapsed_seconds=f'{time.monotonic()-started:.3f}', text=content)
                play_sentences(wire, parts, prepared, followup=followup)
                replied = True
                voice_event('hassmic_playback_finished', streaming=True)
            elif kind == 'done':
                if not replied:
                    raise ValueError('No committed reply')
        if not replied:
            raise ValueError('No committed reply')
    finally:
        if hasattr(stream, 'close'):
            stream.close()
        prepared.close()
