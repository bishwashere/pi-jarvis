import json
import queue
import struct
import wave
from types import SimpleNamespace

import pytest

import echo_audio
import listen_to_mic
import play_audio
from interruptions import WakeWordInterrupted


class Socket:
    def __init__(self, messages=(), path="/control", headers=None):
        self.messages = iter(messages)
        self.sent = []
        self.closed = None
        self.request = SimpleNamespace(path=path, headers=headers)

    def send(self, message):
        self.sent.append(message)

    def recv(self, timeout=None):
        return next(self.messages)

    def __iter__(self):
        return self.messages

    def close(self, *args):
        self.closed = args

    def respond(self, status, body):
        return status, body


def hub():
    h = echo_audio.EchoAudio(host="127.0.0.1", port=0, device_id="test-dot", token="x" * 32)
    h.control, h.data = Socket(), Socket()
    h.start = lambda: None
    return h


def make_wav(tmp_path, samples, rate=16000, channels=1):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as w:
        w.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        w.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return path


def test_pcm_conversion_preserves_duration_and_stereo_mix(tmp_path):
    path = make_wav(tmp_path, [3000, -1000] * 160, channels=2)
    pcm = echo_audio.wav_pcm48(path)
    assert len(pcm) == 480 * 2
    assert set(struct.unpack("<480h", pcm)) == {1000}


def test_pcm_conversion_does_not_wrap_full_scale(tmp_path):
    path = make_wav(tmp_path, [32767, -32768] * 80)
    output = struct.unpack("<480h", echo_audio.wav_pcm48(path))
    assert min(output) == -32768
    assert max(output) == 32767


def test_nested_microphone_consumers_stop_only_after_last_exit():
    h, target = hub(), queue.Queue()
    with h.microphone(target, 16000):
        with h.microphone(target, 16000):
            h._audio(b"\x01\x12\x34")
        assert h.microphone_users == 1
        assert target.get_nowait() == b"\x12\x34"
    commands = [json.loads(m)["type"] for m in h.control.sent]
    assert commands == ["mic_start", "mic_stop"]
    assert h.microphone_queue is None


def test_microphone_rejects_invalid_frames_and_bounds_backlog():
    h, target = hub(), queue.Queue()
    with h.microphone(target, 16000):
        for value in range(30):
            h._audio(b"\x01" + struct.pack("<h", value))
        h._audio(b"\x01\x00")  # incomplete sample
        h._audio(b"\x04")  # VAD event, not audio
        h._audio("not audio")
        assert target.qsize() == 12
        assert target.get_nowait() == struct.pack("<h", 18)
    before = target.qsize()
    h._audio(b"\x01\x00\x00")
    assert target.qsize() == before


def test_microphone_start_failure_releases_consumer():
    h = hub()
    h._send = lambda message: (_ for _ in ()).throw(ConnectionError())
    with pytest.raises(ConnectionError):
        with h.microphone(queue.Queue(), 16000):
            pass
    assert h.microphone_users == 0
    assert h.microphone_queue is None


@pytest.mark.parametrize("path,token,allowed", [
    ("/control", "x" * 32, True),
    ("/data", "x" * 32, True),
    ("/shell/test-dot", "x" * 32, False),
    ("/control", "wrong", False),
    ("/control", None, False),
])
def test_only_audio_channels_with_token_are_accepted(path, token, allowed):
    from websockets.datastructures import Headers
    headers = Headers({"X-EM-Token": token}) if token else Headers()
    socket = Socket(path=path, headers=headers)
    result = hub()._authorize(socket, socket.request)
    assert (result is None) is allowed


def test_wrong_device_cannot_replace_live_control_connection():
    h = hub()
    previous = h.control
    socket = Socket([json.dumps({"type": "register", "device_id": "other"})])
    h._connection(socket)
    assert socket.closed[0] == 1008
    assert h.control is previous


def test_data_reconnect_restores_requested_microphone_stream():
    h, target = hub(), queue.Queue()
    h.data = None
    h.microphone_users, h.microphone_queue = 1, target
    socket = Socket([
        json.dumps({"type": "identify", "device_id": "test-dot"}),
        b"\x01\x01\x00",
    ], path="/data")
    h._connection(socket)
    assert json.loads(h.control.sent[-3]) == {"type": "mic_start", "lock_mic": False}
    assert json.loads(h.control.sent[-2]) == {"type": "beam_unlock"}
    assert json.loads(h.control.sent[-1])["type"] == "leds"
    assert target.get_nowait() == b"\x01\x00"
    assert h.data is None


def test_playback_interruption_flushes_remote_speaker(tmp_path):
    h = hub()
    assert h.play(make_wav(tmp_path, [0] * 160), interrupted=lambda: True) is True
    assert json.loads(h.control.sent[-1]) == {"type": "speaker_flush"}
    assert not h.data.sent


def test_playback_sends_pcm_and_end_marker(tmp_path, monkeypatch, capsys):
    h = hub()
    clock = iter([0, 10])
    monkeypatch.setattr(echo_audio.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(echo_audio.time, "sleep", lambda seconds: None)
    h._wait_connected = lambda: None
    assert h.play(make_wav(tmp_path, [1000] * 160)) is False
    assert h.data.sent[0] == b"\x02" + struct.pack("<480h", *([1000] * 480))
    assert h.data.sent[-1] == b"\x03"
    output = capsys.readouterr().out
    assert output.count("speaker_audio_sent") == 1
    assert "audio_seconds='0.010'" in output


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_echo_dispatch_bypasses_local_audio_hardware(monkeypatch, platform):
    target = object()
    fake = SimpleNamespace(
        microphone=lambda q, rate: target,
        play=lambda path, interrupted: True,
    )
    monkeypatch.setattr(echo_audio, "get_echo", lambda: fake)
    monkeypatch.setattr(listen_to_mic, "AUDIO_DEVICE", "echomuse")
    monkeypatch.setattr(play_audio, "PLAYBACK_BACKEND", "echomuse")
    monkeypatch.setattr(play_audio.sys, "platform", platform)
    assert listen_to_mic.open_microphone_stream() is target
    with pytest.raises(WakeWordInterrupted):
        play_audio.play_wav_file("unused.wav")


@pytest.mark.parametrize("active", [False, True])
def test_wake_ring_restored_on_control_reconnect(active):
    h = hub()
    h.control = None
    h.set_conversation_active(active)
    socket = Socket([json.dumps({"type": "register", "device_id": "test-dot"})])
    h._connection(socket)
    commands = [json.loads(message) for message in socket.sent]
    assert commands[1]["beamformingEnabled"] is True
    assert commands[-3]["type"] == ("mic_start" if active else "mic_stop")
    assert commands[-2]["type"] == ("beam_lock" if active else "beam_unlock")
    ring = json.loads(socket.sent[-1])
    assert ring["type"] == "leds"
    assert ring["listening"] is active
    assert {pixel["id"] for pixel in ring["leds"]} == set(range(12))
    assert all(pixel["r"] == 0 for pixel in ring["leds"])
    assert all(bool(pixel["g"] and pixel["b"]) is active for pixel in ring["leds"])


def test_ring_clears_after_conversation():
    h = hub()
    h.set_conversation_active(True)
    h.set_conversation_active(False)
    assert all(
        pixel["r"] == pixel["g"] == pixel["b"] == 0
        for pixel in json.loads(h.control.sent[-1])["leds"]
    )


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_indicator_skips_non_echo_and_tolerates_failure(monkeypatch, platform):
    monkeypatch.setattr(echo_audio.sys, "platform", platform)
    monkeypatch.setattr(echo_audio, "AUDIO_DEVICE", "default")
    monkeypatch.setattr(echo_audio, "PLAYBACK_BACKEND", "auto")
    calls = []

    def fail():
        calls.append(True)
        raise ConnectionError("offline")

    monkeypatch.setattr(echo_audio, "get_echo", fail)
    echo_audio.set_echo_conversation_active(True)
    assert not calls
    monkeypatch.setattr(echo_audio, "AUDIO_DEVICE", "echomuse")
    echo_audio.set_echo_conversation_active(True)
    assert calls == [True]


def test_direction_survives_wake_greeting_command_gaps():
    h, target = hub(), queue.Queue()
    with h.microphone(target, 16000):
        h.set_conversation_active(True)
    # The recognizer closes during TTS, but the physical stream must stay alive.
    assert h.microphone_users == 0
    h._audio(b"\x01\x01\x00")
    assert target.empty()  # no accumulation while no recognizer is listening
    with h.microphone(target, 16000):
        h._audio(b"\x01\x02\x00")
        assert target.get_nowait() == b"\x02\x00"
    commands = [json.loads(message)["type"] for message in h.control.sent]
    assert commands == ["mic_start", "beam_lock", "leds", "mic_start", "beam_lock"]
    h.set_conversation_active(False)
    commands = [json.loads(message)["type"] for message in h.control.sent]
    assert commands[-3:] == ["beam_unlock", "mic_stop", "leds"]


def test_idle_transition_does_not_stop_nested_consumer():
    h, target = hub(), queue.Queue()
    with h.microphone(target, 16000):
        h.set_conversation_active(True)
        h.set_conversation_active(False)
        assert "mic_stop" not in [json.loads(message)["type"] for message in h.control.sent]
    assert json.loads(h.control.sent[-1])["type"] == "mic_stop"


@pytest.mark.parametrize("score,age,accepted", [
    (0.8, 100, True), (0.2, 0, False), (0.8, 2000, False),
    (float("nan"), 0, False), (0.9, -10, False), (2, 0, False),
])
def test_native_wake_filters_stale_or_invalid_events(monkeypatch, score, age, accepted):
    monkeypatch.setattr(echo_audio, "ECHO_NATIVE_WAKE", True)
    h = hub()
    with h.microphone(queue.Queue(), 16000):
        h._control_message(json.dumps({"type": "oww_wake", "score": score, "ageMs": age}))
        result = h.consume_wake()
        assert (result is not None) is accepted
        assert h.consume_wake() is None


def test_native_wake_cannot_cross_mute_or_consumer_boundaries(monkeypatch):
    monkeypatch.setattr(echo_audio, "ECHO_NATIVE_WAKE", True)
    h = hub()
    event = '{"type":"oww_wake","score":0.9,"ageMs":0}'
    h._control_message(event)
    assert h.consume_wake() is None
    with h.microphone(queue.Queue(), 16000):
        h._control_message(event)
        h._control_message('{"type":"mute_state","muted":true}')
        assert h.consume_wake() is None
        h._control_message(event)
        assert h.consume_wake() is None
        h._control_message('{"type":"mute_state","muted":false}')
        h._control_message(event)
    assert h.consume_wake() is None


def test_native_wake_expires_before_consumption(monkeypatch, capsys):
    monkeypatch.setattr(echo_audio, "ECHO_NATIVE_WAKE", True)
    h = hub()
    h.microphone_users = 1
    clock = iter([100, 102])
    monkeypatch.setattr(echo_audio.time, "monotonic", lambda: next(clock))
    h._control_message('{"type":"oww_wake","score":0.8,"ageMs":0}')
    assert h.consume_wake() is None
    assert "reason='expired_before_consumption'" in capsys.readouterr().out


@pytest.mark.parametrize("score,age,muted,listeners,result", [
    (0.8, 100, False, 1, "queued"),
    (0.2, 0, False, 1, "below_threshold"),
    (0.8, 2000, False, 1, "stale"),
    (0.8, 0, True, 1, "muted"),
    (0.8, 0, False, 0, "no_listener"),
])
def test_native_wake_logs_received_detection_and_disposition(
    monkeypatch, capsys, score, age, muted, listeners, result,
):
    monkeypatch.setattr(echo_audio, "ECHO_NATIVE_WAKE", True)
    h = hub()
    h.muted, h.microphone_users = muted, listeners
    h._control_message(json.dumps({"type": "oww_wake", "score": score, "ageMs": age}))
    output = capsys.readouterr().out
    assert "wake_detection_received detector='openwakeword'" in output
    assert "model='hey_jarvis_v0.1'" in output
    assert f"score='{score}'" in output
    assert f"result='{result}'" in output
    assert "wake_heard" not in output
    assert (h.consume_wake() is not None) is (result == "queued")


@pytest.mark.parametrize("event", [
    '{"type":"oww_wake","score":"invalid","ageMs":0}',
    '{"type":"oww_wake","score":2,"ageMs":0}',
    '{"type":"oww_wake","score":0.9,"ageMs":-1}',
    '{"type":"other","score":0.9,"ageMs":0}',
])
def test_invalid_control_messages_do_not_claim_detection(monkeypatch, capsys, event):
    monkeypatch.setattr(echo_audio, "ECHO_NATIVE_WAKE", True)
    h = hub()
    h.microphone_users = 1
    h._control_message(event)
    assert h.consume_wake() is None
    assert "wake_detection_received" not in capsys.readouterr().out


def test_native_wake_config_is_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(echo_audio, "ECHO_NATIVE_WAKE", True)
    h = hub()
    h.control = None
    socket = Socket([json.dumps({"type": "register", "device_id": "test-dot"})])
    h._connection(socket)
    configuration = json.loads(socket.sent[1])
    assert configuration["owwOnDevice"] == "on"
    assert configuration["owwModel"] == "hey_jarvis_v0.1"
    assert configuration["owwThreshold"] == 0.5
