# Pi Jarvis

Voice assistant runtime for a Raspberry Pi. It listens for a wake word, records a spoken command, sends the command to the configured Jarvis agent API, converts the reply to speech with Piper, and plays it through the configured ALSA output device.

## 1. Install

### 1.1 Python Environment (Raspberry Pi, Mac, Windows)

The project uses `uv` and keeps its environment under `runtime/venv`. From the
project directory, create or update the environment from the lockfile:

```sh
UV_PROJECT_ENVIRONMENT=runtime/venv uv sync --python 3.12 --locked
```

Activate it when running Python commands directly:

```sh
. runtime/venv/bin/activate
```

Nothing is installed into the system Python. Python 3.12 is the tested version;
`uv` can install it locally if the machine does not already have it.

### 1.2 Raspberry Pi System Packages

```sh
sudo apt update
sudo apt install -y alsa-utils portaudio19-dev git make gcc g++ cmake curl
```

### 1.3 Local Whisper

Install `whisper.cpp` outside this project directory:

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

## 2. Run

On the deployed Raspberry Pi, start the production profile:

```sh
./run_jarvis.sh
```

The launcher finds the project directory automatically, uses
`runtime/venv`, prevents duplicate instances with `flock`, and writes to
`logs/jarvis_voice.log`.

For local development without `whisper.cpp` or the Pi-specific ALSA card, use:

```sh
./run_local.sh
```

The local profile selects the bundled Vosk model for command transcription,
the default audio output, and foreground logs. It does not replace the Jarvis
agent backend; point it to a reachable server when necessary:

```sh
JARVIS_API_BASE_URL=http://127.0.0.1:1235/v1/agents/jarvis ./run_local.sh
```

Press `Ctrl+C` to stop either foreground launcher.

## 3. Check

Run the hardware-safe local smoke test. It loads Vosk, exercises response and
wake-word logic, and generates speech with Piper without opening the microphone,
speaker, or network:

```sh
runtime/venv/bin/python self_test.py
```

Run the automated tests, which mock all hardware and network boundaries:

```sh
runtime/venv/bin/python -m pytest
```

Check the agent API from the Pi:

```sh
curl http://192.168.1.82:1235/v1/agents/jarvis/health
```

Check whether Jarvis is running:

```sh
pgrep -af 'jarvis_voice.py|run_jarvis.sh'
```

Follow the live log from `/home/jarvis/jarvis`:

```sh
tail -n 100 -f logs/jarvis_voice.log
```

List audio devices:

```sh
python -m sounddevice
arecord -l
aplay -l
amixer scontrols
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

Test Whisper manually:

```sh
cd /home/jarvis/whisper.cpp
./build/bin/whisper-cli -m models/ggml-tiny.en.bin -f samples/jfk.wav -nt -np -t 1
```

## 4. Start on Boot

Install an `@reboot` cron entry for the `jarvis` user:

```sh
(crontab -l 2>/dev/null; echo '@reboot sleep 20 && /home/jarvis/jarvis/run_jarvis.sh') | crontab -
```

Start it immediately with the same launcher:

```sh
nohup /home/jarvis/jarvis/run_jarvis.sh >/dev/null 2>&1 &
```

## 5. Configuration Reference

Defaults live in `config.py`. Repository assets and logs are resolved from the
checkout automatically. Settings can be overridden without editing code by
using environment variables.

- Microphone input device: `AUDIO_DEVICE = "default"` with fallbacks for `pulse`, `P10S: USB Audio`, `USB Audio`, and index `0`.
- Speaker playback device: `PLAYBACK_DEVICE = "plughw:2,0"`
- ALSA volume card/control: card `2`, control `PCM`, volume `85%`
- Wake words/phrases: `hello jarvis`, `hey jarvis`, `hello computer`, `hey computer`, `jarvis`, `computer`, `hello`
- Lenient wake level: `70`, where `0` only wakes on exact configured phrases and `100` wakes on any recognized speech.
- Command speech-to-text engine: `whisper`; Vosk is still used for wake detection.
- Whisper model: `../whisper.cpp/models/ggml-tiny.en.bin`, relative to the checkout
- Wake response: `Hi. How can I help?`
- Initial command listen window: `60` seconds, with an earlier stop after speech followed by a short silence.
- Follow-up listen window after an answer: `4` seconds.
- Agent API: `http://192.168.1.82:1235/v1/agents/jarvis`
- Vosk model: `runtime/assets/vosk-model-small-en-us-0.15`
- Piper voice model: `runtime/assets/piper/en_US-amy-medium.onnx`

Common environment overrides:

- `JARVIS_PROJECT_DIR`, `JARVIS_VENV_DIR`, `JARVIS_LOG_FILE`, `JARVIS_LOCK_FILE`
- `JARVIS_API_BASE_URL`, `JARVIS_API_URL`, `JARVIS_API_HEALTH_URL`, `JARVIS_API_MODEL`
- `JARVIS_AUDIO_DEVICE`, `JARVIS_AUDIO_DEVICE_FALLBACKS`, `JARVIS_PLAYBACK_DEVICE`
- `JARVIS_CONFIGURE_VOLUME`, `JARVIS_VOLUME_CARD`, `JARVIS_VOLUME_CONTROL`, `JARVIS_VOLUME_LEVEL`
- `JARVIS_COMMAND_STT_ENGINE` (`whisper` or `vosk`)
- `JARVIS_WHISPER_CPP_DIR`, `JARVIS_WHISPER_CPP_BINARY`, `JARVIS_WHISPER_MODEL_PATH`
- `JARVIS_VOSK_MODEL_PATH`, `JARVIS_PIPER_MODEL_PATH`, `JARVIS_PIPER_BINARY`
- `JARVIS_COMMAND_RECORDING_PATH`, `JARVIS_REPLY_WAV_PATH`

## 6. Notes

Jarvis uses Vosk for wake detection and local `whisper.cpp` for command transcription.

The `tiny.en` Whisper model is the smallest practical local Whisper model for this Pi. It is good for testing, but command transcription may still be slower than Vosk because Whisper records the whole command audio clip first, then transcribes it.

On Mac or Windows, Python setup is similar, but the full voice loop still
expects ALSA commands for playback. The hardware-safe `self_test.py` does not.

Jarvis validates that the chosen microphone supports the configured `SAMPLE_RATE` before opening it. If the USB microphone or speaker appears under a different card/device number, update `AUDIO_DEVICE`, `AUDIO_DEVICE_FALLBACKS`, `PLAYBACK_DEVICE`, `VOLUME_CARD`, and `VOLUME_CONTROL`.

## 7. Log Examples

Expected startup output includes:

```text
Loading Vosk model...
Jarvis voice loop running.
Say one of these to wake: hello jarvis, hey jarvis, hello computer, hey computer, jarvis, computer, hello
Lenient wake level: 70
Press Ctrl+C to stop.
Waiting for wake word...
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
Stopped recording after 4.2s: speech followed by 1.2s silence; saved /path/to/pi-jarvis/logs/command.wav (peak rms=4567).
Whisper transcribing /path/to/pi-jarvis/logs/command.wav...
Whisper transcript after 3.3s: 'what is the weather today'
Command: what is the weather today
```

## 8. Project Layout

- `jarvis_voice.py` - main entry point.
- `config.py` - audio devices, wake words, API URL, model paths, timing, and spoken phrases.
- `conversation_loop.py` - wake/listen/ask/speak loop.
- `listen_to_mic.py` - microphone stream using `sounddevice`.
- `speech_to_text.py` and `detect_wake_word.py` - Vosk speech recognition and wake-word detection.
- `call_agent_api.py` - HTTP calls to the Jarvis/Pasture agent API.
- `text_to_speech.py` and `play_audio.py` - Piper TTS and ALSA playback.
- `self_test.py` - local smoke test that avoids hardware, network, and Whisper.
- `run_local.sh` - local development profile using bundled Vosk and default audio.
- `pyproject.toml` and `uv.lock` - reproducible Python dependencies.
- `tests/` - hardware- and network-independent automated tests.
- `runtime/assets/` - local Vosk and Piper model assets copied from the Pi.

## 9. Troubleshooting

- If startup fails with a Vosk model error, confirm `runtime/assets/vosk-model-small-en-us-0.15/` exists and matches `VOSK_MODEL_PATH`.
- If command transcription fails with Whisper errors, confirm the sibling `whisper.cpp/build/bin/whisper-cli` and `whisper.cpp/models/ggml-tiny.en.bin` paths exist, set the corresponding environment overrides, or use `run_local.sh` for Vosk transcription.
- If Whisper records silence even when you speak, lower `COMMAND_AUDIO_RMS_THRESHOLD`; if it records background noise as speech, raise it.
- If TTS fails, confirm `piper` is installed and `PIPER_MODEL_PATH` points to the `.onnx` voice model.
- If the Pi cannot hear commands, run `python -m sounddevice` and update `AUDIO_DEVICE`.
- If audio plays through the wrong speaker, run `aplay -l` and update `PLAYBACK_DEVICE`.
- If the assistant says it cannot reach Pasture, confirm the API host is online and reachable from the Pi.
