"""Portable PCM arrival chime followed by an exact quiet gap and speech."""
import math
import struct
import wave
from pathlib import Path

from config import ANNOUNCEMENT_CHIME_GAP_SECONDS


def prepend_chime(speech_path):
    with wave.open(str(speech_path), 'rb') as source:
        params = source.getparams()
        if params.nchannels != 1 or params.sampwidth != 2:
            raise ValueError('Announcement chime requires mono 16-bit PCM')
        speech = source.readframes(source.getnframes())
    frames = []
    for frequency in (523.25, 659.25, 783.99):
        count = round(params.framerate * .18)
        for i in range(count):
            envelope = math.sin(math.pi * i / max(1, count - 1)) ** 2
            frames.append(round(10000 * envelope * math.sin(2 * math.pi * frequency * i / params.framerate)))
    chime = struct.pack('<' + 'h' * len(frames), *frames)
    gap = bytes(round(params.framerate * ANNOUNCEMENT_CHIME_GAP_SECONDS) * 2)
    output = Path(speech_path).with_name('announcement-chimed.wav')
    with wave.open(str(output), 'wb') as target:
        target.setparams(params)
        target.writeframes(chime + gap + speech)
    return str(output)
