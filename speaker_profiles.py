"""Saved speakers, resolved afresh so reconnects can change device numbers."""

import json
import re
import subprocess
import sys
from pathlib import Path

from config import SPEAKER_PROFILES_PATH


def load_profiles(path=SPEAKER_PROFILES_PATH):
    try:
        profiles = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(profiles, list):
            raise ValueError("expected an ordered list of speaker profiles")
        for profile in profiles:
            if not isinstance(profile, dict):
                raise ValueError("each speaker profile must be an object")
            backend = profile.get("backend", "alsa")
            if backend not in {"alsa", "bluetooth"}:
                raise ValueError("speaker backend must be alsa or bluetooth")
            keys = ("name", "bluetooth_address") if backend == "bluetooth" else (
                "name", "usb_by_id", "volume_control", "volume_level"
            )
            for key in keys:
                if not isinstance(profile.get(key), str) or not profile[key].strip():
                    raise ValueError(f"speaker profile needs a nonempty {key}")
            if backend == "bluetooth":
                if not re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", profile["bluetooth_address"]):
                    raise ValueError("invalid Bluetooth address")
                continue
            if Path(profile["usb_by_id"]).name != profile["usb_by_id"]:
                raise ValueError("usb_by_id must be a device link name")
            if type(profile.get("device")) is not int or profile["device"] < 0:
                raise ValueError("speaker device must be a nonnegative integer")
        return profiles
    except (OSError, ValueError) as error:
        print(f"Cannot load speaker profiles from {path}: {error}", flush=True)
        return []


def resolve_profile(profile, snd_dir=Path("/dev/snd"), asound_dir=Path("/proc/asound")):
    """Match the saved USB serial, then use the current ALSA card ID."""
    if profile.get("backend") == "bluetooth":
        return resolve_bluetooth_profile(profile)
    try:
        control = (snd_dir / "by-id" / profile["usb_by_id"]).resolve(strict=True)
        match = re.fullmatch(r"controlC(\d+)", control.name)
        if not match:
            return None
        card_dir = asound_dir / f"card{match[1]}"
        if not (card_dir / f"pcm{profile['device']}p").is_dir():
            return None
        card = (card_dir / "id").read_text().strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", card):
            return None
        return {
            **profile,
            "card": card,
            "playback_device": f"plughw:CARD={card},DEV={profile['device']}",
        }
    except OSError:
        # Unplugged devices (including a disconnect during detection) are skipped.
        return None


def resolve_bluetooth_profile(profile):
    """Find a connected PipeWire/PulseAudio sink by its Bluetooth address."""
    if not sys.platform.startswith("linux"):
        return None
    prefix = "bluez_output." + profile["bluetooth_address"].upper().replace(":", "_") + "."
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True, text=True, check=True, timeout=2,
        )
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[1].startswith(prefix):
                return {**profile, "playback_device": fields[1]}
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def connected_profiles():
    return [resolved for profile in load_profiles() if (resolved := resolve_profile(profile))]


if __name__ == "__main__":
    for profile in load_profiles():
        resolved = resolve_profile(profile)
        status = resolved["playback_device"] if resolved else "disconnected"
        print(f"{profile['name']}: {status}")
