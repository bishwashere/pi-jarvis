"""Incremental Whisper snapshots; only the final transcript becomes a command."""
import io
from contextvars import copy_context
import json
import socket
import subprocess
import time
import uuid
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

from config import (LOG_DIR, STREAMING_STT_INTERVAL, STREAMING_WHISPER_THREADS,
                    WHISPER_CPP_BINARY, WHISPER_MODEL_PATH, WHISPER_TIMEOUT_SECONDS)
from voice_log import voice_event


def wav_bytes(pcm):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(pcm)
    return output.getvalue()


class WhisperServer:
    """Own a loopback-only model server for this controller's lifetime."""
    def __init__(self):
        self.process = None
        self.log = None

    def start(self):
        binary = Path(WHISPER_CPP_BINARY).with_name(
            'whisper-server.exe' if str(WHISPER_CPP_BINARY).endswith('.exe') else 'whisper-server')
        if not binary.is_file() or binary.stat().st_size == 0:
            raise RuntimeError('Build whisper-server beside whisper-cli to enable streaming')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.url = f'http://127.0.0.1:{port}'
        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
        self.log = open(Path(LOG_DIR) / 'whisper-stream-server.log', 'ab')
        try:
            self.process = subprocess.Popen(
                [str(binary), '-m', str(WHISPER_MODEL_PATH), '-t', str(STREAMING_WHISPER_THREADS),
                 '--host', '127.0.0.1', '--port', str(port)],
                stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError('Whisper server exited; see whisper-stream-server.log')
                try:
                    with urlopen(self.url + '/health', timeout=.5) as response:
                        if json.load(response).get('status') == 'ok':
                            voice_event('streaming_stt_ready', model=Path(WHISPER_MODEL_PATH).name)
                            return self
                except (OSError, ValueError):
                    time.sleep(.1)
            raise TimeoutError('Whisper server startup timed out')
        except BaseException:
            self.close()
            raise

    def transcribe(self, pcm):
        boundary = 'jarvis-' + uuid.uuid4().hex
        fields = [('response_format', b'json', None), ('language', b'en', None),
                  ('temperature', b'0', None), ('file', wav_bytes(pcm), 'command.wav')]
        body = bytearray()
        for name, value, filename in fields:
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'.encode())
            if filename:
                body.extend(f'; filename="{filename}"\r\nContent-Type: audio/wav'.encode())
            body.extend(b'\r\n\r\n' + value + b'\r\n')
        body.extend(f'--{boundary}--\r\n'.encode())
        request = Request(self.url + '/inference', data=bytes(body),
                          headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
        with urlopen(request, timeout=WHISPER_TIMEOUT_SECONDS) as response:
            result = json.load(response)
        if not isinstance(result.get('text'), str):
            raise ValueError('Whisper returned no transcript')
        return result['text'].strip()

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.log:
            self.log.close()


class IncrementalTranscript:
    """One inference at a time; discard outdated drafts, never queue old audio."""
    def __init__(self, transcribe, interval=STREAMING_STT_INTERVAL, on_partial=None):
        self.transcribe = transcribe
        self.on_partial = on_partial
        self.published_future = None
        self.interval = interval
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='whisper-stream')
        self.future = None
        self.submitted_version = None
        self.first_voice = None
        self.latest_pcm = b''
        self.version = None
        self.last_submit = float('-inf')

    def update(self, frames, last_voice, duration):
        self._publish()
        if last_voice is None:
            return
        if self.first_voice is None:
            self.first_voice = max(0, last_voice - .4)
        # Keep a little trailing silence for Whisper but never include subsequent
        # speech without giving the snapshot a new version.
        version = round(min(duration, last_voice + .3) * 16000)
        if version != self.version:
            pcm = b''.join(frames)
            self.latest_pcm = pcm[int(self.first_voice * 16000) * 2:version * 2] + bytes(6400)
            self.version = version
        if (duration - self.first_voice >= .6
                and self.submitted_version != self.version
                and (duration - self.last_submit >= self.interval or duration - last_voice >= .2)
                and (self.future is None or self.future.done())):
            self._submit(duration)

    def _publish(self):
        if self.future is not None and self.future.done() and self.future is not self.published_future:
            self.published_future = self.future
            try:
                text = self.future.result()
                voice_event('streaming_transcript_draft', text=text)
                if self.on_partial is not None:
                    self.on_partial(text)
            except Exception as exc:
                voice_event('streaming_transcript_draft_failed', error=exc)

    def _submit(self, duration):
        if self.future is not None:
            # Only finish() waits for an in-flight snapshot; microphone updates
            # reach this method only after the previous inference has finished.
            try:
                self.future.result()
            except Exception:
                pass
            self._publish()
        self.submitted_version = self.version
        self.last_submit = duration
        self.future = self.pool.submit(copy_context().run, self.transcribe, self.latest_pcm)

    def finish(self):
        if self.version is None:
            return ''
        if self.future is None or self.submitted_version != self.version:
            # At most one stale inference can still be in flight.
            self._submit(self.last_submit)
        return self.future.result()

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
