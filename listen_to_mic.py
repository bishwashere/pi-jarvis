import queue

import sounddevice as sd

from config import AUDIO_DEVICE, AUDIO_DEVICE_FALLBACKS, SAMPLE_RATE


audio_queue = queue.Queue()
selected_audio_device = None


def audio_callback(indata, frames, time_info, status):
    if status:
        print("Audio status:", status)

    audio_queue.put(bytes(indata))


def clear_audio_queue():
    while not audio_queue.empty():
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break


def describe_audio_device(device):
    info = sd.query_devices(device, "input")
    return f"{info['name']} ({info['max_input_channels']} input channels)"


def candidate_audio_devices():
    seen = set()
    for candidate in [AUDIO_DEVICE, *AUDIO_DEVICE_FALLBACKS]:
        key = repr(candidate)
        if key not in seen:
            seen.add(key)
            yield candidate


def query_input_device(candidate):
    try:
        sd.check_input_settings(
            device=candidate,
            channels=1,
            dtype="int16",
            samplerate=SAMPLE_RATE,
        )
        info = sd.query_devices(candidate, "input")
    except Exception as e:
        print(f"Audio input candidate {candidate!r} unavailable: {e}", flush=True)
        return None

    if info.get("max_input_channels", 0) < 1:
        print(f"Audio input candidate {candidate!r} has no input channels.", flush=True)
        return None

    return info


def find_input_device_by_name():
    devices = sd.query_devices()
    hints = [
        str(candidate).lower()
        for candidate in [AUDIO_DEVICE, *AUDIO_DEVICE_FALLBACKS]
        if isinstance(candidate, str) and candidate != "default"
    ]

    for index, info in enumerate(devices):
        name = str(info.get("name", ""))
        if info.get("max_input_channels", 0) < 1:
            continue

        try:
            sd.check_input_settings(
                device=index,
                channels=1,
                dtype="int16",
                samplerate=SAMPLE_RATE,
            )
        except Exception:
            continue

        if any(hint in name.lower() for hint in hints):
            return index, info

    for index, info in enumerate(devices):
        if info.get("max_input_channels", 0) < 1:
            continue

        try:
            sd.check_input_settings(
                device=index,
                channels=1,
                dtype="int16",
                samplerate=SAMPLE_RATE,
            )
        except Exception:
            continue

        return index, info

    return None, None


def resolve_audio_device():
    global selected_audio_device

    if selected_audio_device is not None:
        return selected_audio_device

    for candidate in candidate_audio_devices():
        info = query_input_device(candidate)
        if info:
            selected_audio_device = candidate
            print(
                f"Using audio input device {candidate!r}: "
                f"{info['name']} ({info['max_input_channels']} input channels)",
                flush=True,
            )
            return selected_audio_device

    index, info = find_input_device_by_name()
    if info:
        selected_audio_device = index
        print(
            f"Using fallback audio input device {index}: "
            f"{info['name']} ({info['max_input_channels']} input channels)",
            flush=True,
        )
        return selected_audio_device

    raise RuntimeError("No audio input device with at least one channel was found.")


def reset_audio_device_selection():
    global selected_audio_device
    selected_audio_device = None


def open_microphone_stream():
    device = resolve_audio_device()
    return sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=4000,
        device=device,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    )
