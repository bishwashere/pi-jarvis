"""One Pi runtime with independently reconnecting Echo conversations."""
import signal
import tempfile
import threading
import time
from pathlib import Path

from config import (COMMAND_SERVER_ENABLED, LOG_DIR, STREAMING_ENABLED, VOICE_PROFILE_DIR,
                    ECHO_LOG_MAX_BYTES, ECHO_LOG_BACKUP_COUNT)
from device_context import bind_device
from echo_devices import AnnouncementRouter, DeviceSession, WakeCoordinator, load_devices
from voice_log import voice_event, device_event_log


class SerializedWhisper:
    """Share one loaded model; bound contention to one snapshot per Echo."""
    def __init__(self, server):
        self.server = server
        self.lock = threading.Lock()

    def transcribe(self, pcm):
        with self.lock:
            return self.server.transcribe(pcm)


def run(path):
    from hassmic_jarvis import Announcements, run_connected
    from speech_to_text import transcribe_with_whisper
    from call_agent_api import ask_pasture
    from text_to_speech import synthesize_to_wav
    from jarvis_command_server import start_command_server

    devices, default_id = load_devices(path)
    coordinator = WakeCoordinator()
    sessions = {d.device_id: DeviceSession(d, coordinator) for d in devices}
    queues = {d.device_id: Announcements() for d in devices}
    router = AnnouncementRouter(devices, default_id, queues, sessions)
    stop = threading.Event()
    previous_signals = {}
    def terminate(*_):
        stop.set()
        for session in sessions.values():
            session.stop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous_signals[signum] = signal.signal(signum, terminate)
    whisper = server = None
    threads = []
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    try:
        if STREAMING_ENABLED:
            from streaming_stt import WhisperServer
            whisper = WhisperServer().start()
        shared_whisper = SerializedWhisper(whisper) if whisper else None
        with tempfile.TemporaryDirectory(prefix='multi-echo-', dir=LOG_DIR) as directory:
            if whisper:
                synthesize_to_wav('Ready.', str(Path(directory)/'warmup.wav'))
            if COMMAND_SERVER_ENABLED:
                server = start_command_server(router.handle)
            def worker(device):
                with bind_device(device), device_event_log(
                        Path(LOG_DIR) / 'devices' / f'{device.device_id}.log',
                        max_bytes=ECHO_LOG_MAX_BYTES, backup_count=ECHO_LOG_BACKUP_COUNT):
                    workdir = Path(directory)/device.device_id
                    workdir.mkdir()
                    voice_event('echo_worker_started', name=device.display_name, host=device.host,
                                conversation_id=device.conversation_id, wake_group=device.wake_group)
                    try:
                        run_connected(device.host, device.port, transcribe_with_whisper,
                            ask_pasture, synthesize_to_wav, workdir, queues[device.device_id],
                            streaming_server=shared_whisper, stop_event=stop,
                            session=sessions[device.device_id],
                            setup_root=Path(VOICE_PROFILE_DIR)/device.device_id)
                    except Exception as exc:
                        voice_event('echo_worker_failed', error=exc)
                        stop.set()
            for device in devices:
                thread = threading.Thread(target=worker, args=(device,),
                                          name=f'echo-{device.device_id}', daemon=True)
                threads.append(thread)
                thread.start()
            voice_event('multi_echo_started', devices=','.join(d.device_id for d in devices),
                        default_device_id=default_id)
            try:
                while not stop.wait(.5):
                    if any(not thread.is_alive() for thread in threads):
                        raise RuntimeError('An Echo worker exited unexpectedly')
            finally:
                terminate()
                # Closing Whisper also interrupts blocked local inference requests.
                if whisper:
                    whisper.close()
                deadline = time.monotonic() + 3
                for thread in threads:
                    thread.join(timeout=max(0, deadline - time.monotonic()))
    finally:
        terminate()
        if server:
            server.shutdown()
            server.server_close()
        if whisper:
            whisper.close()
        for signum, handler in previous_signals.items():
            signal.signal(signum, handler)
