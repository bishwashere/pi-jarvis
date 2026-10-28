"""EchoMuse's network microphone and speaker behind Jarvis's audio interfaces.

Wire format: EchoMuse v2.18.1, mono S16_LE at 16 kHz in and 48 kHz out.
Only the two audio/control sockets are served; remote shells aren't supported.
"""
from array import array
from contextlib import contextmanager
import hmac
import json
import math
import queue
import sys
import threading
import time
import wave

from config import (
    AUDIO_DEVICE, PLAYBACK_BACKEND, ECHO_BIND, ECHO_DEVICE_ID, ECHO_PORT, ECHO_TOKEN,
    ECHO_NATIVE_WAKE, ECHO_WAKE_THRESHOLD,
)
from voice_log import voice_event


def wav_pcm48(path):
    """Convert a PCM16 mono/stereo WAV to mono 48 kHz without external tools."""
    with wave.open(str(path), "rb") as wav:
        channels, width, rate = wav.getnchannels(), wav.getsampwidth(), wav.getframerate()
        if width != 2 or channels not in (1, 2) or wav.getcomptype() != "NONE":
            raise ValueError("Echo playback requires an uncompressed PCM16 mono/stereo WAV")
        samples = array("h", wav.readframes(wav.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    if channels == 2:
        samples = array("h", (int((a + b) / 2) for a, b in zip(samples[::2], samples[1::2])))
    if rate != 48000 and samples:
        source = samples
        samples = array("h")
        for index in range(round(len(source) * 48000 / rate)):
            position = index * rate / 48000
            first = min(int(position), len(source) - 1)
            second = min(first + 1, len(source) - 1)
            samples.append(round(source[first] + (source[second] - source[first]) * (position - first)))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


class EchoAudio:
    def __init__(self, *, host, port, device_id, token):
        if not device_id or len(token) < 32:
            raise ValueError("Echo audio requires a device ID and a token of at least 32 characters")
        self.host, self.port, self.device_id, self.token = host, port, device_id, token
        self.condition = threading.Condition(threading.RLock())
        self.play_lock = threading.Lock()
        self.control = self.data = self.server = None
        self.microphone_queue = None
        self.microphone_users = 0
        self.thread = None
        self.start_error = None
        self.started = threading.Event()
        self.conversation_active = False
        self.pending_wake = None
        self.muted = False

    def _control_message(self, raw):
        """Accept only fresh acoustic detections from the authenticated device."""
        if not ECHO_NATIVE_WAKE:
            return
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                return
            if message.get("type") == "mute_state" and isinstance(message.get("muted"), bool):
                with self.condition:
                    self.muted = message["muted"]
                    self.pending_wake = None
                return
            if message.get("type") != "oww_wake":
                return
            score, age = float(message["score"]), float(message["ageMs"])
            if not (math.isfinite(score) and math.isfinite(age)):
                return
            if not (0 <= score <= 1 and age >= 0):
                return
        except (ValueError, TypeError, KeyError):
            return
        with self.condition:
            if score < ECHO_WAKE_THRESHOLD:
                result = "below_threshold"
            elif age > 1500:
                result = "stale"
            elif self.muted:
                result = "muted"
            elif not self.microphone_users:
                result = "no_listener"
            else:
                result = "queued"
                self.pending_wake = (time.monotonic() - age / 1000, score)
            voice_event(
                "wake_detection_received", detector="openwakeword",
                model="hey_jarvis_v0.1", score=score, age_ms=age,
                threshold=ECHO_WAKE_THRESHOLD, result=result,
            )

    def consume_wake(self):
        with self.condition:
            pending, self.pending_wake = self.pending_wake, None
            if pending and time.monotonic() - pending[0] <= 1.5:
                return pending[1]
            if pending:
                voice_event(
                    "wake_detection_ignored", detector="openwakeword",
                    score=pending[1], reason="expired_before_consumption",
                )
        return None

    def _send_wake_light(self):
        self._send({
            "type": "leds",
            "listening": self.conversation_active,
            "leds": [
                {"id": index, "r": 0, "g": 96 if self.conversation_active else 0,
                 "b": 160 if self.conversation_active else 0}
                for index in range(12)
            ],
        })

    def set_conversation_active(self, active):
        """Lock onto the speaker at wake, retaining that mic for the whole turn."""
        with self.condition:
            if self.conversation_active == bool(active):
                return
            self.conversation_active = bool(active)
            if self.control is not None:
                self._send({"type": "beam_lock" if active else "beam_unlock"})
                if not active and not self.microphone_users:
                    self._send({"type": "mic_stop"})
                self._send_wake_light()
                print(f"Echo conversation {'active: directional mic' if active else 'idle: centre mic'}",
                      flush=True)

    def start(self):
        with self.condition:
            if self.thread is None:
                self.thread = threading.Thread(target=self._serve, daemon=True)
                self.thread.start()
        if not self.started.wait(10):
            raise TimeoutError("Echo audio listener did not start")
        if self.start_error:
            raise RuntimeError("Echo audio listener failed") from self.start_error

    def _serve(self):
        try:
            from websockets.sync.server import serve
            with serve(
                self._connection, self.host, self.port, max_size=262144,
                max_queue=16, ping_interval=20, ping_timeout=30,
                process_request=self._authorize,
            ) as server:
                self.server = server
                self.started.set()
                print(f"Echo audio listening on {self.host}:{self.port}", flush=True)
                server.serve_forever()
        except Exception as error:
            self.start_error = error
            self.started.set()
            with self.condition:
                self.condition.notify_all()

    def _authorize(self, connection, request):
        tokens = request.headers.get_all("X-EM-Token")
        if (
            request.path not in ("/control", "/data")
            or len(tokens) != 1
            or not hmac.compare_digest(tokens[0], self.token)
        ):
            return connection.respond(403, "Forbidden\n")

    def _send(self, payload):
        if self.control is None:
            raise ConnectionError("Echo control channel is disconnected")
        self.control.send(json.dumps(payload))

    def _connection(self, connection):
        channel = None
        try:
            first = json.loads(connection.recv(timeout=10))
            expected = "register" if connection.request.path == "/control" else "identify"
            if first.get("device_id") != self.device_id or first.get("type") != expected:
                connection.close(1008, "Unexpected device")
                return
            channel = "control" if expected == "register" else "data"
            with self.condition:
                if getattr(self, channel) is not None:
                    connection.close(1008, "Channel already connected")
                    return
                setattr(self, channel, connection)
                if channel == "control":
                    self._send({"type": "ack", "device_id": self.device_id, "features": []})
                    self._send({
                        "type": "config", "owwOnDevice": "on" if ECHO_NATIVE_WAKE else "off",
                        "owwModel": "hey_jarvis_v0.1", "owwThreshold": ECHO_WAKE_THRESHOLD,
                        "wakeWordEnabled": True,
                        "bleProxyEnabled": False, "sendspinEnabled": False,
                        "aecEnabled": True, "beamformingEnabled": True,
                    })
                if self.control is not None and self.data is not None:
                    self._send({"type": "mic_start" if (
                        self.microphone_users or self.conversation_active
                    ) else "mic_stop",
                                "lock_mic": False})
                    self._send({"type": "beam_lock" if self.conversation_active else "beam_unlock"})
                    self._send_wake_light()
                    print(f"Echo audio connected: {self.device_id}", flush=True)
                self.condition.notify_all()
            for message in connection:
                if channel == "data":
                    self._audio(message)
                else:
                    self._control_message(message)
                # EchoMuse responds to WebSocket pings itself. Its telemetry
                # and button events don't carry assistant commands.
        except Exception as error:
            print(f"Echo {channel or 'handshake'} connection ended: {type(error).__name__}", flush=True)
        finally:
            with self.condition:
                if channel and getattr(self, channel) is connection:
                    setattr(self, channel, None)
                    self.pending_wake = None
                    self.condition.notify_all()

    def _audio(self, message):
        if not isinstance(message, bytes) or message[:1] != b"\x01":
            return
        pcm = message[1:]
        if not pcm or len(pcm) % 2:
            return
        with self.condition:
            target = self.microphone_queue if self.microphone_users else None
            if target is None:
                return
            # Bound the existing shared queue to about two seconds. Never
            # accumulate minutes of stale microphone audio during a slow call.
            while target.qsize() >= 12:
                try:
                    target.get_nowait()
                except queue.Empty:
                    break
            target.put_nowait(pcm)

    def _wait_connected(self, timeout=30):
        self.start()
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.control is None or self.data is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Waiting for Echo audio over Wi-Fi")
                self.condition.wait(min(remaining, 1))

    @contextmanager
    def microphone(self, target, sample_rate):
        if sample_rate != 16000:
            raise ValueError("Echo microphone requires 16 kHz audio")
        self._wait_connected()
        with self.condition:
            if self.microphone_users and self.microphone_queue is not target:
                raise RuntimeError("Echo microphone already has another consumer")
            self.microphone_queue = target
            self.microphone_users += 1
            try:
                if self.microphone_users == 1:
                    self._send({"type": "mic_start", "lock_mic": False})
                    if self.conversation_active:
                        self._send({"type": "beam_lock"})
            except Exception:
                self.microphone_users -= 1
                if not self.microphone_users:
                    self.microphone_queue = None
                    self.pending_wake = None
                raise
        try:
            yield self
        finally:
            with self.condition:
                self.microphone_users -= 1
                if not self.microphone_users:
                    self.microphone_queue = None
                    self.pending_wake = None
                    # Restarting between wake, greeting and command would
                    # discard the direction chosen from the wake phrase.
                    # Audio received without a consumer is discarded by _audio.
                    if not self.conversation_active:
                        try:
                            self._send({"type": "mic_stop"})
                        except Exception:
                            pass

    def play(self, path, *, interrupted=lambda: False):
        pcm = wav_pcm48(path)
        if not pcm:
            return False
        with self.play_lock:
            self._wait_connected()
            with self.condition:
                data = self.data
            start = time.monotonic()
            try:
                for offset in range(0, len(pcm), 4096):
                    if interrupted():
                        self._send({"type": "speaker_flush"})
                        return True
                    if self.data is not data or self.control is None:
                        raise ConnectionError("Echo disconnected during playback")
                    data.send(b"\x02" + pcm[offset:offset + 4096])
                    if offset == 0:
                        voice_event(
                            "speaker_audio_sent", backend="echomuse",
                            audio_seconds=f"{len(pcm) / 96000:.3f}",
                        )
                    # Deliver at 2x playback speed, as EchoMuse's controller does.
                    time.sleep(4096 / 96000 / 2)
                data.send(b"\x03")
                # Include the firmware's roughly one-second priming buffer.
                end = start + len(pcm) / 96000 + 1.2
                while time.monotonic() < end:
                    if self.data is not data or self.control is None:
                        raise ConnectionError("Echo disconnected during playback")
                    if interrupted():
                        self._send({"type": "speaker_flush"})
                        return True
                    time.sleep(0.03)
                return False
            except Exception:
                try:
                    self._send({"type": "speaker_flush"})
                except Exception:
                    pass
                raise


_echo = None
_echo_lock = threading.Lock()


def get_echo():
    global _echo
    with _echo_lock:
        if _echo is None:
            _echo = EchoAudio(
                host=ECHO_BIND, port=ECHO_PORT, device_id=ECHO_DEVICE_ID, token=ECHO_TOKEN,
            )
        return _echo


def set_echo_conversation_active(active):
    """Best-effort Echo mic selection and ring feedback; other hardware is unchanged."""
    if str(AUDIO_DEVICE).lower() != "echomuse" and PLAYBACK_BACKEND != "echomuse":
        return
    try:
        get_echo().set_conversation_active(active)
    except Exception as error:
        print(f"Echo conversation controls unavailable: {type(error).__name__}", flush=True)


def consume_echo_wake():
    if not ECHO_NATIVE_WAKE or str(AUDIO_DEVICE).lower() != "echomuse":
        return None
    return get_echo().consume_wake()
