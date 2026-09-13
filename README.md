# Pi Jarvis

Voice assistant runtime for a Raspberry Pi. It listens for a wake word, records a spoken command, sends the command to the configured Jarvis agent API, converts the reply to speech with Piper, and plays it through the configured ALSA output device.

## Project Layout

- `jarvis_voice.py` - main entry point.
- `config.py` - audio devices, wake words, API URL, model paths, timing, and spoken phrases.
- `conversation_loop.py` - wake/listen/ask/speak loop.
- `listen_to_mic.py` - microphone stream using `sounddevice`.
- `speech_to_text.py` and `detect_wake_word.py` - Vosk speech recognition and wake-word detection.
- `call_agent_api.py` - HTTP calls to the Jarvis/Pasture agent API.
- `text_to_speech.py` and `play_audio.py` - Piper TTS and ALSA playback.
- `runtime/assets/` - local Vosk and Piper model assets copied from the Pi.

## Raspberry Pi Setup

From the Pi:

```sh
cd /home/jarvis/jarvis
```

Create or activate a Python environment:

```sh
python3 -m venv runtime/venv
. runtime/venv/bin/activate
python -m pip install --upgrade pip
python -m pip install requests vosk sounddevice piper-tts
```

Install system audio tools and PortAudio support:

```sh
sudo apt update
sudo apt install -y alsa-utils portaudio19-dev git make gcc g++ cmake curl
```

The project expects the Piper executable to be available as `piper`:

```sh
piper --help
```

## Local Whisper Setup

Jarvis uses Vosk for wake detection and local `whisper.cpp` for command transcription. Install `whisper.cpp` outside this project directory:

```sh
cd /home/jarvis
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
make -j2
./models/download-ggml-model.sh tiny.en
```

Confirm the Whisper binary and model exist:

```sh
ls -lh /home/jarvis/whisper.cpp/build/bin/whisper-cli
ls -lh /home/jarvis/whisper.cpp/models/ggml-tiny.en.bin
```

Run a sample transcription:

```sh
cd /home/jarvis/whisper.cpp
./build/bin/whisper-cli -m models/ggml-tiny.en.bin -f samples/jfk.wav -nt -np -t 1
```

Expected transcript:

```text
And so my fellow Americans ask not what your country can do for you, ask what you can do for your country.
```

The `tiny.en` model is the smallest practical local Whisper model for this Pi. It is good for testing, but command transcription may still be slower than Vosk because Whisper records the whole command audio clip first, then transcribes it.

## Configuration

Edit `config.py` if your Pi hardware or API host changes.

Current defaults:

- Microphone input device: `AUDIO_DEVICE = "default"` with fallbacks for `pulse`, `P10S: USB Audio`, `USB Audio`, and index `0`.
- Speaker playback device: `PLAYBACK_DEVICE = "plughw:2,0"`
- ALSA volume card/control in `play_audio.py`: card `2`, control `PCM`, volume `85%`
- Wake words/phrases: `hello jarvis`, `hey jarvis`, `hello computer`, `hey computer`, `jarvis`, `computer`, `hello`
- Lenient wake level: `70`, where `0` only wakes on exact configured phrases and `100` wakes on any recognized speech.
- Command speech-to-text engine: `whisper`; Vosk is still used for wake detection.
- Whisper model: `/home/jarvis/whisper.cpp/models/ggml-tiny.en.bin`
- Wake response: `Hi. How can I help?`
- Initial command listen window: `60` seconds, with an earlier stop after speech followed by a short silence.
- If no command is heard after wake, Jarvis logs the timeout and quietly returns to wake-word mode.
- If a wake phrase is repeated during command listening, Jarvis logs it and keeps listening quietly.
- Follow-up listen window after an answer: `4` seconds.
- Agent API: `http://192.168.1.82:1235/v1/agents/jarvis`
- Vosk model: `/home/jarvis/jarvis/runtime/assets/vosk-model-small-en-us-0.15`
- Piper voice model: `/home/jarvis/jarvis/runtime/assets/piper/en_US-amy-medium.onnx`

To list audio devices:

```sh
python -m sounddevice
arecord -l
aplay -l
amixer scontrols
```

Jarvis validates that the chosen microphone supports the configured `SAMPLE_RATE` before opening it. If the USB microphone or speaker appears under a different card/device number, update `AUDIO_DEVICE`, `AUDIO_DEVICE_FALLBACKS`, `PLAYBACK_DEVICE`, `VOLUME_CARD`, and `VOLUME_CONTROL`.

## Run

Start the voice assistant:

```sh
cd /home/jarvis/jarvis
. runtime/venv/bin/activate
python jarvis_voice.py
```

Or use the launcher script, which sets the venv path, writes logs, and uses a lock so duplicate Jarvis loops do not start:

```sh
cd /home/jarvis/jarvis
./run_jarvis.sh
```

Expected startup output includes:

```text
Loading Vosk model...
Jarvis voice loop running.
Say one of these to wake: hello jarvis, hey jarvis, hello computer, hey computer, jarvis, computer, hello
Lenient wake level: 70
Press Ctrl+C to stop.
Waiting for wake word...
```

Say one of the configured wake words or phrases, wait for the prompt, then speak a command. Press `Ctrl+C` to stop.

In Whisper command mode, Jarvis records the command as `logs/command.wav`, waits for speech followed by silence or the configured timeout, transcribes the finished audio clip with local `whisper.cpp`, then sends the transcript to Pasture.

## Start on Boot

Install an `@reboot` cron entry for the `jarvis` user:

```sh
(crontab -l 2>/dev/null; echo '@reboot sleep 20 && /home/jarvis/jarvis/run_jarvis.sh') | crontab -
```

Start it immediately with the same launcher:

```sh
nohup /home/jarvis/jarvis/run_jarvis.sh >/dev/null 2>&1 &
```

Check whether it is running:

```sh
pgrep -af 'jarvis_voice.py|run_jarvis.sh'
tail -n 80 /home/jarvis/jarvis/logs/jarvis_voice.log
```

Follow the live log from `/home/jarvis/jarvis`:

```sh
tail -n 100 -f logs/jarvis_voice.log
```

The log includes what speech recognition heard, what was sent to the Pasture API, and what came back:

```text
Command: news headlines
[2026-09-12T17:45:00] Pasture request: {'model': 'api-assistant', 'user': 'news headlines'}
[2026-09-12T17:45:02] Pasture response: {'raw': '...', 'parsed': {'reply': '...', 'continue_listening': False}}
Jarvis: ...
Listening for command for up to 4 seconds...
Stopped listening after 4.0s: no speech heard.
No follow-up after 4.0s (listen window: 4s). Returning to wake word mode.
```

In Whisper command mode, command capture looks like this:

```text
Listening for command with Whisper for up to 60 seconds...
Recording command audio for up to 60 seconds...
Whisper command recording detected speech after 1.0s (rms=1234).
Stopped recording after 4.2s: speech followed by 1.2s silence; saved /home/jarvis/jarvis/logs/command.wav (peak rms=4567).
Whisper transcribing /home/jarvis/jarvis/logs/command.wav...
Whisper transcript after 3.3s: 'what is the weather today'
Command: what is the weather today
```

## Quick Checks

Check the agent API from the Pi:

```sh
curl http://192.168.1.82:1235/v1/agents/jarvis/health
```

Test speaker playback:

```sh
aplay -D plughw:2,0 logs/reply.wav
```

Test Piper manually:

```sh
echo "Jarvis is online." | piper --model runtime/assets/piper/en_US-amy-medium.onnx --output_file /tmp/jarvis-test.wav
aplay -D plughw:2,0 /tmp/jarvis-test.wav
```

## Troubleshooting

- If startup fails with a Vosk model error, confirm `runtime/assets/vosk-model-small-en-us-0.15/` exists and matches `VOSK_MODEL_PATH`.
- If command transcription fails with Whisper errors, confirm `/home/jarvis/whisper.cpp/build/bin/whisper-cli` and `/home/jarvis/whisper.cpp/models/ggml-tiny.en.bin` exist and match `WHISPER_CPP_BINARY` / `WHISPER_MODEL_PATH`.
- If Whisper records silence even when you speak, lower `COMMAND_AUDIO_RMS_THRESHOLD`; if it records background noise as speech, raise it.
- If TTS fails, confirm `piper` is installed and `PIPER_MODEL_PATH` points to the `.onnx` voice model.
- If the Pi cannot hear commands, run `python -m sounddevice` and update `AUDIO_DEVICE`.
- If audio plays through the wrong speaker, run `aplay -l` and update `PLAYBACK_DEVICE`.
- If the assistant says it cannot reach Pasture, confirm the API host is online and reachable from the Pi.
