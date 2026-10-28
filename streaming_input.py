"""Stream revisable transcripts upstream; only an explicit final commit can act."""
import json
from contextvars import copy_context
from device_context import conversation_id as current_conversation_id, request_headers
import threading
import time

import requests

from config import API_URL, API_MODEL, API_CONVERSATION_ID
from voice_log import voice_event


class StreamingInput:
    """One chunked HTTP upload per utterance, with at most one queued revision."""
    def __init__(self):
        self.conversation_id = current_conversation_id()
        self.headers = request_headers()
        self.condition = threading.Condition()
        self.pending = None
        self.last_text = None
        self.thread = None
        self.ready = threading.Event()
        self.response = None
        self.error = None
        self.committed = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def partial(self, text):
        from speech_to_text import clean_command_transcript
        text = clean_command_transcript(text, log=False)
        if not text:
            return
        with self.condition:
            if self.closed or self.committed or text == self.last_text or self.error:
                return
            self.last_text = text
            self.pending = {'type': 'partial', 'text': text}
            if self.thread is None:
                self.thread = threading.Thread(target=copy_context().run, args=(self._upload,), name='pasture-input', daemon=True)
                self.thread.start()
            self.condition.notify_all()

    def _body(self):
        yield (json.dumps({'type': 'start', 'conversation_id': self.conversation_id,
                          'model': API_MODEL}) + '\n').encode()
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None)
                event, self.pending = self.pending, None
            yield (json.dumps(event) + '\n').encode()
            if event['type'] != 'partial':
                return
            voice_event('streaming_input_partial_sent', text=event['text'])

    def _upload(self):
        try:
            response = requests.post(API_URL, headers={
                'Content-Type': 'application/x-ndjson', 'Accept': 'text/event-stream',
                'X-Pasture-Conversation-Id': self.conversation_id, **self.headers,
            }, data=self._body(), stream=True, timeout=(5, 90))
            with self.condition:
                if self.closed:
                    response.close()
                else:
                    self.response = response
                    response.raise_for_status()
        except Exception as exc:
            self.error = exc
        finally:
            self.ready.set()

    def events(self, text):
        from streaming_reply import api_events, response_events
        with self.condition:
            # Nothing committed yet: a failed provisional upload is safe to
            # abandon and replace with the existing single final request.
            fallback = self.thread is None or self.error is not None or self.ready.is_set()
            if not fallback:
                self.committed = True
                self.pending = {'type': 'commit', 'text': text}
                self.condition.notify_all()
        if fallback:
            self.close()
            voice_event('streaming_input_fallback', reason='no_live_upload')
            yield from api_events(text)
            return
        voice_event('streaming_input_committed', text=text)
        started = time.monotonic()
        if not self.ready.wait(95):
            raise TimeoutError('Pasture upload did not complete')
        if self.error:
            # Commit may have reached the server. Never replay a possible action.
            raise self.error
        if self.response is None:
            raise RuntimeError('Pasture upload closed before reply')
        voice_event('streaming_input_response_started', elapsed_seconds=f'{time.monotonic()-started:.3f}')
        try:
            yield from response_events(self.response)
        finally:
            self.response.close()

    def close(self):
        with self.condition:
            self.closed = True
            if not self.committed:
                self.pending = {'type': 'cancel'}
            self.condition.notify_all()
        if self.response is not None:
            self.response.close()
        if self.thread is not None:
            self.thread.join(timeout=1)
