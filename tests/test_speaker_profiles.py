import json
import subprocess
from types import SimpleNamespace

import pytest

import play_audio
import speaker_profiles


@pytest.fixture
def profile():
    return {
        "name": "Test speaker",
        "usb_by_id": "usb-Test_123-00",
        "device": 0,
        "volume_control": "PCM",
        "volume_level": "85%",
    }


def test_usb_identity_survives_card_renumbering(tmp_path, profile):
    snd = tmp_path / "snd"
    (snd / "by-id").mkdir(parents=True)
    asound = tmp_path / "asound"
    link = snd / "by-id" / profile["usb_by_id"]
    for number in (2, 5):
        (snd / f"controlC{number}").touch()
        card = asound / f"card{number}"
        (card / "pcm0p").mkdir(parents=True)
        (card / "id").write_text("P10S\n")
        link.unlink(missing_ok=True)
        link.symlink_to(snd / f"controlC{number}")
        resolved = speaker_profiles.resolve_profile(profile, snd, asound)
        assert resolved["playback_device"] == "plughw:CARD=P10S,DEV=0"
        assert resolved["card"] == "P10S"
    link.unlink()
    assert speaker_profiles.resolve_profile(profile, snd, asound) is None


def test_capture_only_device_is_not_a_speaker(tmp_path, profile):
    (tmp_path / "by-id").mkdir()
    (tmp_path / "controlC2").touch()
    (tmp_path / "by-id" / profile["usb_by_id"]).symlink_to(tmp_path / "controlC2")
    (tmp_path / "card2").mkdir()
    (tmp_path / "card2/id").write_text("P10S")
    assert speaker_profiles.resolve_profile(profile, tmp_path, tmp_path) is None


@pytest.mark.parametrize("contents", ["{", "{}", '[null]', '[{"name": "bad"}]'])
def test_invalid_profiles_fail_safely(tmp_path, contents):
    path = tmp_path / "profiles.json"
    path.write_text(contents)
    assert speaker_profiles.load_profiles(path) == []


def test_missing_profile_file_is_safe(tmp_path):
    assert speaker_profiles.load_profiles(tmp_path / "missing.json") == []


def test_load_profile_list_preserves_order(tmp_path, profile):
    path = tmp_path / "profiles.json"
    profiles = [profile, {**profile, "name": "Second speaker"}]
    path.write_text(json.dumps(profiles))
    assert speaker_profiles.load_profiles(path) == profiles


@pytest.mark.parametrize("with_monitor", [False, True])
def test_playback_cycles_profiles_then_default(monkeypatch, profile, with_monitor):
    profiles = [
        {**profile, "card": card, "playback_device": f"plughw:CARD={card},DEV=0"}
        for card in ("P10S", "Other")
    ]
    monkeypatch.setattr(play_audio, "PLAYBACK_DEVICE", "profiles")
    monkeypatch.setattr(play_audio, "connected_profiles", lambda: profiles)
    monkeypatch.setattr(play_audio, "PLAYBACK_FALLBACK_DEVICES", ["default"])
    volumes = []
    monkeypatch.setattr(play_audio, "ensure_speaker_volume", lambda p: volumes.append(p))
    monkeypatch.setattr(play_audio, "WakeWordMonitor", lambda model: object())
    attempted = []

    def popen(args, **kwargs):
        attempted.append(args[2])
        code = 0 if args[2] == "default" else 1
        return SimpleNamespace(
            returncode=code, communicate=lambda: ("", "unavailable"), poll=lambda: code
        )

    monkeypatch.setattr(play_audio.subprocess, "Popen", popen)
    play_audio.play_wav_with_alsa("reply.wav", model=object() if with_monitor else None)
    assert attempted == [p["playback_device"] for p in profiles] + ["default"]
    assert volumes == profiles


def test_success_stops_profile_search(monkeypatch, profile):
    resolved = {**profile, "card": "P10S", "playback_device": "plughw:CARD=P10S,DEV=0"}
    monkeypatch.setattr(play_audio, "PLAYBACK_DEVICE", "profiles")
    monkeypatch.setattr(play_audio, "connected_profiles", lambda: [resolved])
    monkeypatch.setattr(play_audio, "CONFIGURE_VOLUME", False)
    attempted = []

    def popen(args, **kwargs):
        attempted.append(args[2])
        return SimpleNamespace(returncode=0, communicate=lambda: ("", ""))

    monkeypatch.setattr(play_audio.subprocess, "Popen", popen)
    play_audio.play_wav_with_alsa("reply.wav")
    assert attempted == [resolved["playback_device"]]


def test_no_connected_profiles_uses_default_without_changing_mixer(monkeypatch):
    monkeypatch.setattr(play_audio, "PLAYBACK_DEVICE", "profiles")
    monkeypatch.setattr(play_audio, "connected_profiles", lambda: [])
    monkeypatch.setattr(play_audio, "ensure_speaker_volume", lambda *args: pytest.fail("mixer"))
    attempted = []

    def popen(args, **kwargs):
        attempted.append(args[2])
        return SimpleNamespace(returncode=0, communicate=lambda: ("", ""))

    monkeypatch.setattr(play_audio.subprocess, "Popen", popen)
    play_audio.play_wav_with_alsa("reply.wav")
    assert attempted == ["default"]


def test_profile_mixer_uses_stable_card_and_respects_overrides(monkeypatch, profile):
    monkeypatch.setattr(play_audio, "CONFIGURE_VOLUME", True)
    monkeypatch.setattr(play_audio, "SPEAKER_VOLUME_OVERRIDES", {"level": "45%"})
    commands = []
    monkeypatch.setattr(play_audio.subprocess, "run", lambda args, **kwargs: commands.append(args))
    play_audio.ensure_speaker_volume({**profile, "card": "P10S"})
    assert commands == [["amixer", "-c", "P10S", "sset", "PCM", "45%"]]


def test_explicit_alsa_device_does_not_probe_profiles(monkeypatch):
    monkeypatch.setattr(play_audio, "PLAYBACK_DEVICE", "custom")
    monkeypatch.setattr(play_audio, "CONFIGURE_VOLUME", False)
    monkeypatch.setattr(play_audio, "connected_profiles", lambda: pytest.fail("profile probe"))
    monkeypatch.setattr(
        play_audio.subprocess, "Popen",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, communicate=lambda: ("", "")),
    )
    play_audio.play_wav_with_alsa("reply.wav")


@pytest.fixture
def echo():
    return {
        "name": "Echo test",
        "backend": "bluetooth",
        "bluetooth_address": "00:11:22:33:44:55",
    }


def test_load_mixed_profiles(tmp_path, profile, echo):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps([profile, echo]))
    assert speaker_profiles.load_profiles(path) == [profile, echo]
    echo["bluetooth_address"] = "invalid"
    path.write_text(json.dumps([echo]))
    assert speaker_profiles.load_profiles(path) == []


@pytest.mark.parametrize("suffix", ["1", "23"])
def test_bluetooth_sink_suffix_can_change(monkeypatch, echo, suffix):
    monkeypatch.setattr(speaker_profiles, "sys", SimpleNamespace(platform="linux"))
    name = f"bluez_output.00_11_22_33_44_55.{suffix}"
    monkeypatch.setattr(
        speaker_profiles.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=f"12\tbluez_output.11_22_33_44_55_66.1\tPipeWire\n13\t{name}\tPipeWire\n"
        ),
    )
    assert speaker_profiles.resolve_profile(echo)["playback_device"] == name


@pytest.mark.parametrize("failure", [
    FileNotFoundError(), subprocess.TimeoutExpired("pactl", 2),
    subprocess.CalledProcessError(1, "pactl"),
])
def test_unavailable_pulse_server_skips_echo(monkeypatch, echo, failure):
    monkeypatch.setattr(speaker_profiles, "sys", SimpleNamespace(platform="linux"))
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(speaker_profiles.subprocess, "run", fail)
    assert speaker_profiles.resolve_profile(echo) is None


def test_disconnected_echo_is_not_resolved(monkeypatch, echo):
    monkeypatch.setattr(speaker_profiles, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(
        speaker_profiles.subprocess, "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="1 auto_null PipeWire\n"),
    )
    assert speaker_profiles.resolve_profile(echo) is None


def test_windows_does_not_probe_bluetooth_sink(monkeypatch, echo):
    monkeypatch.setattr(speaker_profiles, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(
        speaker_profiles.subprocess, "run", lambda *a, **k: pytest.fail("pactl on Windows")
    )
    assert speaker_profiles.resolve_profile(echo) is None


@pytest.mark.parametrize("with_monitor", [False, True])
def test_bluetooth_uses_explicit_paplay_sink_without_alsa_mixer(monkeypatch, echo, with_monitor):
    sink = "bluez_output.00_11_22_33_44_55.1"
    monkeypatch.setattr(play_audio, "PLAYBACK_DEVICE", "profiles")
    monkeypatch.setattr(play_audio, "connected_profiles", lambda: [{**echo, "playback_device": sink}])
    monkeypatch.setattr(play_audio, "ensure_speaker_volume", lambda *a: pytest.fail("ALSA mixer"))
    monkeypatch.setattr(play_audio, "WakeWordMonitor", lambda *a: object())
    commands = []
    def popen(args, **kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, communicate=lambda: ("", ""), poll=lambda: 0)
    monkeypatch.setattr(play_audio.subprocess, "Popen", popen)
    play_audio.play_wav_with_alsa("reply.wav", model=object() if with_monitor else None)
    assert commands == [["paplay", f"--device={sink}", "reply.wav"]]


def test_missing_paplay_falls_back(monkeypatch, echo):
    monkeypatch.setattr(play_audio, "PLAYBACK_DEVICE", "profiles")
    monkeypatch.setattr(
        play_audio, "connected_profiles", lambda: [{**echo, "playback_device": "echo-sink"}]
    )
    commands = []
    def popen(args, **kwargs):
        commands.append(args)
        if args[0] == "paplay":
            raise FileNotFoundError("paplay")
        return SimpleNamespace(returncode=0, communicate=lambda: ("", ""))
    monkeypatch.setattr(play_audio.subprocess, "Popen", popen)
    play_audio.play_wav_with_alsa("reply.wav")
    assert commands == [
        ["paplay", "--device=echo-sink", "reply.wav"],
        ["aplay", "-D", "default", "reply.wav"],
    ]
