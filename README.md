# Pi Jarvis

Voice assistant runtime for Raspberry Pi, Linux, and 64-bit Windows. It listens
for a wake word, records a spoken command, sends the command to the configured
Jarvis agent API, converts the reply to speech with Piper, and plays it through
the platform's configured audio output.

## 1. Install

### 1.1 Python Environment (Raspberry Pi, Linux, Windows)

The project uses `uv` and keeps its environment under `runtime/venv`. Python
3.12 is the tested version.

On Raspberry Pi or Linux, run:

```sh
UV_PROJECT_ENVIRONMENT=runtime/venv uv sync --python 3.12 --locked
. runtime/venv/bin/activate
```

On 64-bit Windows, install the latest
[Microsoft Visual C++ x64 Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170)
first; ONNX Runtime requires the Visual C++ runtime. Then run in PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "runtime/venv"
uv sync --python 3.12 --locked
```

Nothing is installed into the system Python. `uv` can install Python 3.12
locally if the machine does not already have it. The lockfile contains compatible
Windows x64 artifacts for CPython 3.10 through 3.14; runtime tests are performed
on Linux, so real Windows microphone and speaker hardware should still be tested.

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

For local Linux development without `whisper.cpp` or the Pi-specific ALSA card,
use:

```sh
./run_local.sh
```

On Windows PowerShell, use the native launcher:

```powershell
.\run_local.ps1
```

The local profile selects the bundled Vosk model for command transcription,
the default audio output, and foreground logs. It does not replace the Jarvis
agent backend; point it to a reachable server when necessary:

```sh
JARVIS_API_BASE_URL=http://127.0.0.1:1235/v1/agents/jarvis ./run_local.sh
```

The PowerShell equivalent is:

```powershell
$env:JARVIS_API_BASE_URL = "http://127.0.0.1:1235/v1/agents/jarvis"
.\run_local.ps1
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

On Windows PowerShell, the equivalent checks are:

```powershell
.\runtime\venv\Scripts\python.exe self_test.py
.\runtime\venv\Scripts\python.exe -m pytest
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

List PortAudio devices on Linux:

```sh
runtime/venv/bin/python -m sounddevice
```

On Windows PowerShell:

```powershell
.\runtime\venv\Scripts\python.exe -m sounddevice
```

On Linux, inspect the underlying ALSA devices and controls:

```sh
arecord -l
aplay -l
amixer scontrols
```

Test Linux speaker playback:

```sh
aplay -D plughw:2,0 logs/reply.wav
```

Test Piper manually on Linux:

```sh
echo "Jarvis is online." | piper --model runtime/assets/piper/en_US-amy-medium.onnx --output_file /tmp/jarvis-test.wav
aplay -D plughw:2,0 /tmp/jarvis-test.wav
```

Test Whisper manually on the Pi/Linux deployment:

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

For manual control after installing `bin/jarvis` to `/usr/local/bin/jarvis`:

```sh
jarvis stop
jarvis start
jarvis restart
jarvis status
jarvis logs
```

## 5. Configuration Reference

Defaults live in `config.py`. Repository assets and logs are resolved from the
checkout automatically. Settings can be overridden without editing code by
using environment variables.

- Microphone input device: `AUDIO_DEVICE = "default"` with fallbacks for `pulse`, `P10S: USB Audio`, `USB Audio`, and index `0`.
- Playback backend: automatic (`alsa` on Linux, `sounddevice` on Windows)
- Speaker playback device: `plughw:2,0` on Linux and the system default elsewhere
- Linux ALSA volume card/control: card `2`, control `PCM`, volume `85%`
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
- `JARVIS_AUDIO_DEVICE`, `JARVIS_AUDIO_DEVICE_FALLBACKS`
- `JARVIS_PLAYBACK_BACKEND` (`auto`, `alsa`, or `sounddevice`), `JARVIS_PLAYBACK_DEVICE`
- `JARVIS_CONFIGURE_VOLUME`, `JARVIS_VOLUME_CARD`, `JARVIS_VOLUME_CONTROL`, `JARVIS_VOLUME_LEVEL`
- `JARVIS_COMMAND_STT_ENGINE` (`whisper` or `vosk`)
- `JARVIS_WHISPER_CPP_DIR`, `JARVIS_WHISPER_CPP_BINARY`, `JARVIS_WHISPER_MODEL_PATH`
- `JARVIS_VOSK_MODEL_PATH`, `JARVIS_PIPER_MODEL_PATH`, `JARVIS_PIPER_BINARY`
- `JARVIS_COMMAND_RECORDING_PATH`, `JARVIS_REPLY_WAV_PATH`

## 6. Notes

Jarvis uses Vosk for wake detection and local `whisper.cpp` for command transcription.

The `tiny.en` Whisper model is the smallest practical local Whisper model for this Pi. It is good for testing, but command transcription may still be slower than Vosk because Whisper records the whole command audio clip first, then transcribes it.

Windows uses PortAudio playback through `sounddevice`; Linux keeps the existing
ALSA `aplay` path. The PowerShell launcher selects Vosk so Windows does not
require a separate `whisper.cpp` build for local testing.

Jarvis validates that the chosen microphone supports the configured `SAMPLE_RATE` before opening it. If the USB microphone or speaker appears under a different card/device number, update `AUDIO_DEVICE`, `AUDIO_DEVICE_FALLBACKS`, `PLAYBACK_DEVICE`, `VOLUME_CARD`, and `VOLUME_CONTROL`.

## 7. Local Command Endpoint

Jarvis can accept local commands from Home Assistant or another trusted client.
By default it listens on `127.0.0.1:8765` only:

```bash
curl http://127.0.0.1:8765/health
```

Queue a phrase into the normal Jarvis voice loop:

```bash
curl -X POST http://127.0.0.1:8765/command \
  -H 'Content-Type: application/json' \
  -d '{"command":"speak","text":"Welcome home."}'
```

Or send just an instruction/message to speak:

```bash
curl -X POST http://127.0.0.1:8765/command \
  -H 'Content-Type: application/json' \
  -d '{"instruction":"Welcome home."}'
```

Jarvis speaks the queued text with the same playback and voice-event logging as
normal replies, then opens the regular follow-up listen window. If the user
answers, that command goes through the usual command capture, Pasture API, reply,
and follow-up loop. If the user stays silent, Jarvis naturally returns to wake
listening.

To let Home Assistant call it over the LAN, set `JARVIS_COMMAND_SERVER_HOST=0.0.0.0`
and set `JARVIS_COMMAND_SERVER_TOKEN`. Jarvis refuses to bind outside localhost
without a token. Send the token as either `Authorization: Bearer <token>` or
`X-Jarvis-Token: <token>`.

## 8. Scripted Conversation Simulation

To test the wake-to-reply conversation path without the microphone, speaker, or
local command endpoint, run the scripted simulator:

```bash
runtime/venv/bin/python simulate_conversation.py \
  "hey jarvis" \
  "what time is it"
```

Reusable suites live in `simulation_suites/`:

```bash
runtime/venv/bin/python simulate_conversation.py \
  --suite simulation_suites/basic_wake_turn.json
```

The weather follow-up suite is:

```bash
runtime/venv/bin/python simulate_conversation.py \
  --suite simulation_suites/weather_followup.json
```

By default this uses a fake API reply and muted playback, but it still runs
through wake matching, wake reply selection, command cleanup, normal command
handling, reply handling, follow-up timeout behavior, and voice-event logs. Add
timing flags to mimic the time between wake and command:

```bash
runtime/venv/bin/python simulate_conversation.py \
  --command-delay 2 \
  --fake-api-latency 1.5 \
  "hey jarvis" \
  "what time is it"
```

To call the configured Jarvis/Pasture API while keeping microphone and speaker
out of the loop:

```bash
runtime/venv/bin/python simulate_conversation.py --real-api \
  "hey jarvis" \
  "what time is it"
```

Use `--summary-json` when you want machine-readable timing output.
Use `--audio-mode synthesize` to run Piper/TTS conversion while still skipping
speaker playback.

## 9. Log Examples

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

## 10. Project Layout

- `jarvis_voice.py` - main entry point.
- `config.py` - audio devices, wake words, API URL, model paths, timing, and spoken phrases.
- `conversation_loop.py` - wake/listen/ask/speak loop.
- `jarvis_command_server.py` - local HTTP command endpoint for Home Assistant.
- `listen_to_mic.py` - microphone stream using `sounddevice`.
- `speech_to_text.py` and `detect_wake_word.py` - Vosk speech recognition and wake-word detection.
- `call_agent_api.py` - HTTP calls to the Jarvis/Pasture agent API.
- `text_to_speech.py` and `play_audio.py` - Piper TTS and cross-platform playback.
- `self_test.py` - local smoke test that avoids hardware, network, and Whisper.
- `run_local.sh` - local development profile using bundled Vosk and default audio.
- `run_local.ps1` - equivalent native Windows PowerShell launcher.
- `pyproject.toml` and `uv.lock` - reproducible Python dependencies.
- `tests/` - hardware- and network-independent automated tests.
- `runtime/assets/` - local Vosk and Piper model assets copied from the Pi.

## 11. Troubleshooting

- If startup fails with a Vosk model error, confirm `runtime/assets/vosk-model-small-en-us-0.15/` exists and matches `VOSK_MODEL_PATH`.
- If command transcription fails with Whisper errors, confirm the sibling `whisper.cpp/build/bin/whisper-cli` and `whisper.cpp/models/ggml-tiny.en.bin` paths exist, set the corresponding environment overrides, or use the platform's local launcher for Vosk transcription.
- If Whisper records silence even when you speak, lower `COMMAND_AUDIO_RMS_THRESHOLD`; if it records background noise as speech, raise it.
- If TTS fails, confirm `piper` is installed and `PIPER_MODEL_PATH` points to the `.onnx` voice model.
- If Jarvis cannot hear commands, use the platform-specific `sounddevice` command above and update `AUDIO_DEVICE`.
- If audio plays through the wrong speaker on Linux, run `aplay -l` and update `PLAYBACK_DEVICE`. On Windows, use the `sounddevice` command above and set `JARVIS_PLAYBACK_DEVICE` to the desired name or index.
- If Windows blocks the PowerShell launcher, allow scripts only for the current shell with `Set-ExecutionPolicy -Scope Process Bypass`, then run `.\run_local.ps1` again.
- Windows x64 is supported by the locked native packages; Windows ARM and 32-bit Windows are not currently validated.
- If the assistant says it cannot reach Pasture, confirm the API host is online and reachable from the machine running Jarvis.
