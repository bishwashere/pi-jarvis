"""Experimental direct hassmic controller. No Home Assistant or local mic needed.

Requires the pinned Echo-side follow-up patch. Not used by jarvis_voice.py.
"""
import argparse
from contextlib import ExitStack
import json
import queue
import select
import signal
import socket
import tempfile
import time
import wave
from pathlib import Path

from config import (COMMAND_AUDIO_RMS_THRESHOLD, COMMAND_SILENCE_SECONDS,
                    FOLLOWUP_SECONDS, HASSMIC_HOST, HASSMIC_PORT, LOG_DIR, ECHO_DEVICES_PATH,
                    HASSMIC_WAKE_WAIT_SECONDS, HASSMIC_FOLLOWUP_WAIT_SECONDS,
                    COMMAND_SERVER_ENABLED, STAND_DOWN_SECONDS, STREAMING_ENABLED, STREAMING_INPUT_ENABLED)
from voice_log import voice_event


class Wire:
    def __init__(self, sock):
        self.sock = sock
        # Detect a powered-off satellite even while idle (no incoming wake).
        # AF_UNIX socket pairs used by tests do not support TCP options.
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for name, value in [('TCP_KEEPIDLE', 15), ('TCP_KEEPINTVL', 5),
                                ('TCP_KEEPCNT', 3)]:
                option = getattr(socket, name, None)
                if option is not None:
                    sock.setsockopt(socket.IPPROTO_TCP, option, value)
        # No read-ahead: idle polling must not overlook buffered wake events.
        self.reader = sock.makefile('rb', buffering=0)

    def close(self):
        self.reader.close()
        self.sock.close()

    def send(self, kind, data=None, payload=b''):
        body = json.dumps(data or {}).encode()
        head = {'type': kind, 'data_length': len(body), 'payload_length': len(payload)}
        self.sock.sendall(json.dumps(head).encode() + b'\n' + body + payload)

    def exact(self, size):
        chunks = []
        while size:
            data = self.reader.read(size)
            if not data:
                raise EOFError('Echo disconnected during an event')
            chunks.append(data)
            size -= len(data)
        return b''.join(chunks)

    def ready(self, timeout):
        return bool(select.select([self.sock], [], [], timeout)[0])

    def receive(self):
        line = self.reader.readline(8193)
        if not line:
            raise EOFError('Echo disconnected')
        if len(line) > 8192 or not line.endswith(b'\n'):
            raise ValueError('Invalid Wyoming header')
        header = json.loads(line)
        lengths = [header.get('data_length', 0), header.get('payload_length', 0)]
        for length, limit in zip(lengths, (8192, 1024 * 1024)):
            if type(length) is not int or not 0 <= length <= limit:
                raise ValueError('Invalid Wyoming event length')
        data = json.loads(self.exact(lengths[0])) if lengths[0] else header.get('data', {})
        if not isinstance(data, dict) or not isinstance(header.get('type'), str):
            raise ValueError('Invalid Wyoming event')
        return header['type'], data, self.exact(lengths[1])

    def next_event(self):
        while True:
            kind, data, payload = self.receive()
            if kind == 'ping':
                self.send('pong')
                continue
            if kind == 'error':
                raise RuntimeError(f'Echo protocol error: {data.get("code", "unknown")}')
            return kind, data, payload


def capture(wire, destination, seconds, *, threshold=COMMAND_AUDIO_RMS_THRESHOLD,
            silence=COMMAND_SILENCE_SECONDS, incremental=None, no_speech_seconds=None):
    from speech_to_text import calculate_rms
    frames = []
    duration = 0.0
    last_voice = None
    voiced_run = 0.0
    started = time.monotonic()
    deadline = started + seconds
    no_speech_seconds = seconds if no_speech_seconds is None else min(seconds, no_speech_seconds)
    while duration < seconds and time.monotonic() < deadline:
        if last_voice is None and (duration >= no_speech_seconds
                                  or time.monotonic() - started >= no_speech_seconds):
            break
        kind, data, pcm = wire.next_event()
        if kind == 'run-pipeline':
            raise RuntimeError('New wake during capture; restarting connection')
        if kind != 'audio-chunk':
            continue
        if (data.get('rate'), data.get('width'), data.get('channels')) != (16000, 2, 1) or len(pcm) % 2:
            raise ValueError('Expected mono 16 kHz signed 16-bit PCM')
        block_seconds = len(pcm) / 32000
        duration += block_seconds
        frames.append(pcm)
        if calculate_rms(pcm) >= threshold:
            voiced_run += block_seconds
            if last_voice is None and voiced_run >= .12:
                voice_event('hassmic_speech_started', after_seconds=f'{duration:.3f}')
                last_voice = duration
            elif last_voice is not None:
                last_voice = duration
        else:
            voiced_run = 0.0
        if incremental is not None:
            incremental.update(frames, last_voice, duration)
        if last_voice is not None and duration - last_voice >= silence:
            break
    # Transcript stops the satellite microphone; silence is never sent to STT.
    if last_voice is None:
        wire.send('error', {'code': 'stt-no-text-recognized'})
        voice_event('hassmic_standby', reason='no_speech')
        return False
    wire.send('transcript', {'text': ''})
    with wave.open(str(destination), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b''.join(frames))
    voice_event('hassmic_capture_finished', audio_seconds=f'{duration:.3f}')
    return True


def play(wire, path, followup):
    with wave.open(str(path), 'rb') as audio:
        if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
            raise ValueError('Expected mono 16-bit response WAV')
        wire.send('audio-start', {'rate': audio.getframerate(), 'width': 2, 'channels': 1})
        while pcm := audio.readframes(1024):
            wire.send('audio-chunk', payload=pcm)
        wire.send('audio-stop', {'jarvis_followup': int(followup)})
    # Socket timeout and disconnect are fatal; never reuse partially read framing.
    while True:
        kind, _, _ = wire.next_event()
        if kind == 'played':
            return
        if kind == 'run-pipeline':
            raise RuntimeError('New wake interrupted response; reconnect required')


class Announcements:
    def __init__(self):
        self.pending = queue.Queue(maxsize=64)
        self.connected = False

    def handle(self, payload):
        command = str(payload.get('command') or payload.get('action') or '').replace('_', ' ').strip().lower()
        text = str(payload.get('text') or payload.get('instruction') or payload.get('message') or '').strip()
        if command == 'status':
            return {'ok': True, 'status': 'running', 'echo_connected': self.connected,
                    'pending_announcements': self.pending.qsize()}
        if command not in {'', 'speak', 'say'}:
            return {'ok': False, 'error': f'unknown command: {command}'}
        if not text:
            return {'ok': False, 'error': 'text, instruction, or message is required'}
        followup = payload.get('followup', True)
        if type(followup) is not bool:
            return {'ok': False, 'error': 'followup must be a boolean'}
        options = {key: payload.get(key, False) for key in ('one_reply', 'chime')}
        if any(type(value) is not bool for value in options.values()):
            return {'ok': False, 'error': 'one_reply and chime must be booleans'}
        try:
            item = text if followup else {'text': text, 'followup': False}
            if any(options.values()):
                item = {'text': text, 'followup': followup, **options}
            self.pending.put_nowait(item)
        except queue.Full:
            return {'ok': False, 'error': 'announcement queue is full'}
        voice_event('command_server_queued', text=text)
        return {'ok': True, 'queued': True, 'text': text}


def log_loaded_wake_models(info):
    """Report loader evidence, never Wyoming's legacy hard-coded wake-word name."""
    models = info.get('satellite', {}).get('loaded_wake_models')
    if models is None:
        voice_event('wake_models_unverified', reason='echo_does_not_report_loaded_models')
        return
    if not isinstance(models, list) or len(models) > 2:
        voice_event('wake_models_unverified', reason='invalid_model_report')
        return
    if not models:
        voice_event('wake_models_unverified', reason='no_micro_wake_models_loaded')
        return
    # Validate the complete report before claiming any model loaded.
    slots = set()
    for model in models:
        if not isinstance(model, dict):
            voice_event('wake_models_unverified', reason='invalid_model_report')
            return
        digest = model.get('sha256', '')
        slot = model.get('slot')
        cutoff = model.get('cutoff')
        window = model.get('window')
        if (type(slot) is not int or slot not in (0, 1) or slot in slots
                or not isinstance(model.get('name'), str) or not model['name']
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)
                or type(cutoff) not in (int, float) or not .5 <= cutoff <= .99
                or type(window) is not int or not 1 <= window <= 20):
            voice_event('wake_models_unverified', reason='invalid_model_report')
            return
        slots.add(slot)
    for model in models:
        voice_event('wake_model_loaded', detector='on_echo', name=model['name'],
                    slot=model['slot'], sha256=model['sha256'],
                    cutoff=model['cutoff'], window=model['window'])


def serve(wire, transcribe, ask, synthesize, directory, *, max_turns=None, announcements=None,
          streaming_server=None, session=None, setup_root=None):
    from conversation_loop import (is_end_session_command, is_stand_down_command,
                                   stand_down_remaining, start_stand_down)
    if session is not None:
        stand_down_remaining = session.stand_down_remaining
        start_stand_down = session.start_stand_down
    wire.send('describe')
    kind, info, _ = wire.next_event()
    if kind != 'info' or info.get('satellite', {}).get('supports_jarvis_followup') is not True:
        raise RuntimeError('Echo needs the Jarvis follow-up patch; refusing single-turn fallback')
    # The timer lives outside this connection, so reconnects cannot undo quiet mode.
    paused = stand_down_remaining() > 0
    wire.send('pause-satellite' if paused else 'run-satellite')
    if announcements is not None:
        announcements.connected = True
    voice_event('hassmic_connected', status='standing_down' if paused else 'waiting_for_wake')
    log_loaded_wake_models(info)
    followup = False
    one_reply = False
    arrival_prompt = ''
    turns = 0
    waiting_logged = False
    while max_turns is None or turns < max_turns:
        if session is not None and not followup:
            session.release()
        remaining = stand_down_remaining()
        if remaining > 0:
            if not paused:
                wire.send('pause-satellite')
                paused = True
                voice_event('hassmic_stand_down_paused', seconds=remaining)
            followup = False
            waiting_logged = False
            wire.sock.settimeout(30)
            # Keep the link alive without recording or delivering announcements.
            if wire.ready(min(1.0, remaining)):
                kind, data, _ = wire.receive()
                if kind == 'ping':
                    wire.send('pong')
                elif kind == 'run-pipeline':
                    wire.send('error', {'code': 'stt-no-text-recognized'})
                    wire.send('pause-satellite')
                    voice_event('hassmic_wake_ignored', reason='standing_down')
                elif kind == 'error':
                    raise RuntimeError(f'Echo protocol error: {data.get("code", "unknown")}')
            continue
        if paused:
            wire.send('run-satellite')
            paused = False
            voice_event('hassmic_stand_down_finished')
        if not followup and not waiting_logged:
            voice_event('wake_listen_started', detector='on_echo', transport='wyoming')
            waiting_logged = True
        # Idle can last indefinitely; only an active exchange has a deadline.
        wire.sock.settimeout(None if announcements is None else 30)
        if announcements is not None and not followup:
            # Give a pending wake priority; never interleave announcement PCM
            # with capture or an existing response on the single Echo socket.
            if not wire.ready(.25):
                try:
                    announcement = announcements.pending.get_nowait()
                except queue.Empty:
                    continue
                text = announcement if isinstance(announcement, str) else announcement['text']
                listen_after = isinstance(announcement, str) or announcement['followup']
                one_reply = not isinstance(announcement, str) and announcement.get('one_reply', False)
                arrival_prompt = text if one_reply else ''
                voice_event('command_server_instruction_started', text=text)
                try:
                    path = synthesize(text, str(Path(directory) / 'announcement.wav'))
                    if not isinstance(announcement, str) and announcement.get('chime', False):
                        from announcement_audio import prepend_chime
                        path = prepend_chime(path)
                    play(wire, path, followup=listen_after)
                    voice_event('command_server_instruction_finished', text=text)
                    followup = listen_after
                except Exception as exc:
                    # Playback might already have happened. Do not replay an
                    # uncertain announcement after reconnecting.
                    voice_event('command_server_instruction_failed', text=text, error=exc)
                    raise
                finally:
                    announcements.pending.task_done()
                continue
        kind, data, _ = wire.next_event()
        if kind != 'run-pipeline':
            continue
        if data.get('start_stage') != 'asr':
            raise ValueError('Configure on-Echo wake detection, not remote wake')
        if session is not None and not session.acquire():
            wire.send('error', {'code': 'stt-no-text-recognized'})
            voice_event('echo_wake_suppressed', reason='listening_group_busy',
                        wake_group=session.device.wake_group)
            followup = False
            continue
        if not followup:
            one_reply = False
            # This satellite hardcodes wake_word_name='alexa', even with MWW.
            # Log the actual trigger without presenting that field as evidence.
            voice_event('wake_heard', detector='on_echo', source='run-pipeline')
        waiting_logged = False
        wire.sock.settimeout(30)
        no_speech_seconds = HASSMIC_FOLLOWUP_WAIT_SECONDS if followup else HASSMIC_WAKE_WAIT_SECONDS
        voice_event('hassmic_listen_started', followup=followup,
                    seconds=FOLLOWUP_SECONDS if followup else 25,
                    no_speech_seconds=no_speech_seconds)
        with ExitStack() as turn_resources:
            upstream = None
            if streaming_server is not None and STREAMING_INPUT_ENABLED and not one_reply:
                from streaming_input import StreamingInput
                upstream = turn_resources.enter_context(StreamingInput())
            clip = Path(directory) / 'command.wav'
            incremental = None
            if streaming_server is not None:
                from streaming_stt import IncrementalTranscript
                incremental = IncrementalTranscript(streaming_server.transcribe,
                    **({'on_partial': upstream.partial} if upstream else {}))
            try:
                if not capture(wire, clip, FOLLOWUP_SECONDS if followup else 25,
                               no_speech_seconds=no_speech_seconds,
                               **({'incremental': incremental} if incremental else {})):
                    followup = False
                    continue
                started = time.monotonic()
                if incremental is None:
                    text = transcribe(str(clip))
                else:
                    from speech_to_text import clean_command_transcript
                    try:
                        text = clean_command_transcript(incremental.finish())
                        voice_event('streaming_transcript_final', text=text)
                    except Exception as exc:
                        voice_event('streaming_stt_fallback', error=exc)
                        text = transcribe(str(clip))
            finally:
                if incremental is not None:
                    incremental.close()
            voice_event('hassmic_command', turn=turns + 1, text=text,
                        transcription_seconds=f'{time.monotonic() - started:.3f}')
            if not text:
                wire.send('error', {'code': 'stt-no-text-recognized'})
                voice_event('hassmic_standby', reason='empty_transcript')
                followup = False
                continue
            from voice_setup import is_setup_command, run_setup
            if is_setup_command(text):
                run_setup(wire, transcribe, synthesize, play,
                          **({'root': setup_root} if setup_root else {}))
                followup = False
                continue
            if is_stand_down_command(text):
                voice_event('stand_down_command', kind='followup' if followup else 'initial', text=text)
                start_stand_down(STAND_DOWN_SECONDS)
                followup = False
                wire.send('error', {'code': 'stt-no-text-recognized'})
                wire.send('pause-satellite')
                paused = True
                waiting_logged = False
                voice_event('hassmic_stand_down_paused', seconds=stand_down_remaining())
                continue
            if is_end_session_command(text):
                voice_event('session_end_command', kind='followup' if followup else 'initial', text=text)
                # Local stop: no spoken acknowledgement or backend session-reset request.
                wire.send('error', {'code': 'stt-no-text-recognized'})
                followup = False
                continue
            reply_text = text
            if one_reply:
                reply_text = (f'Arrival greeting just spoken: {arrival_prompt}\n'
                              f'User response: {text}\n\n'
                              '[Arrival conversation: answer this request briefly, then finish. '
                               'Do not ask a follow-up question.]')
            listen_after_reply = not one_reply
            if streaming_server is not None:
                from streaming_reply import stream_reply
                stream_reply(wire, reply_text, synthesize, directory,
                             **({'followup': False} if one_reply else {}),
                             **({'events': upstream.events} if upstream else {}))
                turns += 1
                followup = listen_after_reply
                continue
            reply = ask(reply_text)
            ready = time.monotonic()
            voice_event('hassmic_response_received', turn=turns + 1)
            path = synthesize(reply['reply'], str(Path(directory) / 'reply.wav'))
            voice_event('hassmic_reply', turn=turns + 1, text=reply['reply'])
            voice_event('hassmic_playback_sent', response_to_send_seconds=f'{time.monotonic() - ready:.3f}')
            play(wire, path, followup=listen_after_reply)
            voice_event('hassmic_playback_finished', turn=turns + 1)
            turns += 1
            followup = listen_after_reply


def run_connected(host, port, transcribe, ask, synthesize, directory, announcements,
                  *, connect=socket.create_connection, wait=time.sleep, streaming_server=None,
                  session=None, stop_event=None, setup_root=None):
    while stop_event is None or not stop_event.is_set():
        wire = None
        try:
            wire = Wire(connect((host, port), timeout=5 if stop_event is not None else 30))
            if session is not None:
                session.attach(wire.sock)
            serve(wire, transcribe, ask, synthesize, directory, announcements=announcements,
                  **({'streaming_server': streaming_server} if streaming_server else {}),
                  **({'session': session, 'setup_root': setup_root} if session else {}))
        except Exception as exc:
            # A failed synthesis/API call must not take down the receive API.
            # Reconnect to reset any partially completed satellite exchange.
            voice_event('hassmic_disconnected', error=exc, retry_seconds=5)
        finally:
            announcements.connected = False
            if session is not None:
                session.detach()
            if wire is not None:
                wire.close()
        if stop_event is not None:
            stop_event.wait(5)
        else:
            wait(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--devices', default=ECHO_DEVICES_PATH, help='Echo registry JSON; enables multi-Echo mode')
    parser.add_argument('--host', default=HASSMIC_HOST)
    parser.add_argument('--port', type=int, default=HASSMIC_PORT)
    args = parser.parse_args()
    if args.devices:
        from multi_echo import run
        run(args.devices)
        return
    if not args.host:
        parser.error('Set JARVIS_HASSMIC_HOST or --host to the Echo address')
    from speech_to_text import transcribe_with_whisper
    from call_agent_api import ask_pasture
    from text_to_speech import synthesize_to_wav
    from jarvis_command_server import start_command_server
    announcements = Announcements()
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    streaming_server = None
    if STREAMING_ENABLED:
        from streaming_stt import WhisperServer
        # Let normal launcher SIGTERM run finally blocks and reap our model server.
        def terminate(_signum, _frame):
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, terminate)
        streaming_server = WhisperServer().start()
    server = None
    with tempfile.TemporaryDirectory(prefix='hassmic-', dir=LOG_DIR) as directory:
        try:
            server = start_command_server(announcements.handle) if COMMAND_SERVER_ENABLED else None
            if streaming_server is not None:
                # Load the configured Piper voice without playing a startup greeting.
                synthesize_to_wav('Ready.', str(Path(directory) / 'warmup.wav'))
            run_connected(args.host, args.port, transcribe_with_whisper, ask_pasture,
                          synthesize_to_wav, directory, announcements,
                          **({'streaming_server': streaming_server} if streaming_server else {}))
        finally:
            if streaming_server is not None:
                streaming_server.close()
            if server is not None:
                server.shutdown()
                server.server_close()


if __name__ == '__main__':
    main()
