# Jarvis: a voice assistant that lives in my house

Jarvis is a small voice assistant that runs on a Raspberry Pi at home. You say its name, ask a question or give a command out loud, and it answers in a natural voice. Speech is handled on the device itself as much as possible, and the request is then passed to an AI agent for the actual thinking.

The front end is the Pi with its microphone and speaker: it listens for the wake word and transcribes speech locally. The back end is a small Python service that forwards commands to the agent and speaks the replies. The technical documentation follows below.

---

# Pi Jarvis

Voice assistant runtime for Raspberry Pi, Linux, and 64-bit Windows. It listens
for a wake word, records a spoken command, sends the command to the configured
Jarvis agent API, converts the reply to speech with Piper, and plays it through
the platform's configured audio output.

## Hardware configurations and component responsibilities

Echo is optional. Use a compatible microphone and speaker attached to the Pi,
or a supported, modified Echo running satellite software. A stock Alexa device
does not automatically provide the satellite connection.

| Stage | Microphone and speaker attached to Pi | Echo satellite |
| --- | --- | --- |
| Capture and microphone processing | Microphone; cleanup depends on hardware/software | Echo microphones and audio front end |
| Wake detection | Vosk on the Pi | microWakeWord on Echo; Pi waits for its wake signal |
| Deliver command audio | Local Pi audio input | Echo streams PCM to Pi over Wyoming |
| Speech/silence timing and follow-ups | Pi Jarvis | Pi Jarvis |
| Command speech recognition | Whisper / whisper.cpp on Pi | Whisper / whisper.cpp on Pi |
| Understand requests, use tools, generate answers | Pasture (backend server) | Pasture (backend server) |
| Generate speech | Piper on Pi | Piper on Pi |
| Play speech | Connected speaker | Pi sends audio to Echo speaker |

The direct-microphone production path records the command before Whisper
transcription. Incremental transcription and input/response streaming are
implemented in the Echo controller path. Local development profiles can use
Vosk for command transcription instead of Whisper.

Echo support adds a Wyoming controller, satellite patches for follow-up and
playback coordination, device routing, reconnect handling, and per-device logs.
Prepare each Echo and register its identity before use; normal reconnects are
automatic. Home Assistant can also submit event-driven announcements directly
to Pi Jarvis for Piper synthesis and playback. The Mac is a development and
maintenance machine, outside the normal voice path.

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
cd /home/<user>
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
make -j2
./models/download-ggml-model.sh tiny.en
```

Confirm the Whisper binary and model exist:

```sh
ls -lh /home/<user>/whisper.cpp/build/bin/whisper-cli
ls -lh /home/<user>/whisper.cpp/models/ggml-tiny.en.bin
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

Check the command center from the Mac or another LAN client:

```sh
curl http://<PI_LAN_IP>:8765/health
```

Check whether Jarvis is running:

```sh
pgrep -af 'jarvis_voice.py|run_jarvis.sh'
```

Follow the live log from `/home/<user>/jarvis`:

```sh
tail -n 100 -F logs/jarvis_voice.log
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
aplay -D <audio-device> logs/reply.wav
```

Test Piper manually on Linux:

```sh
echo "Jarvis is online." | piper --model runtime/assets/piper/en_US-amy-medium.onnx --output_file /tmp/jarvis-test.wav
aplay -D <audio-device> /tmp/jarvis-test.wav
```

Test Whisper manually on the Pi/Linux deployment:

```sh
cd /home/<user>/whisper.cpp
./build/bin/whisper-cli -m models/ggml-tiny.en.bin -f samples/jfk.wav -nt -np -t 1
```

## 4. Start on Boot

Install an `@reboot` cron entry for the `jarvis` user:

```sh
(crontab -l 2>/dev/null; echo '@reboot sleep 20 && /home/<user>/jarvis/run_jarvis.sh') | crontab -
```

Start it immediately with the same launcher:

```sh
nohup /home/<user>/jarvis/run_jarvis.sh >/dev/null 2>&1 &
```

For manual control after installing `bin/jarvis` to `/usr/local/bin/jarvis`:

```sh
jarvis stop
jarvis start
jarvis restart
jarvis status
jarvis logs
```

From this checkout on the Mac, use the repository SSH wrapper for remote Pi
checks. It reads `RASPBERRY_PI_SSH` from `.env` and uses `.ssh_askpass`, so do
not substitute another host/user or add `BatchMode=yes`. In Codex, this is a
LAN network command, so run it with escalated network permissions on the first
attempt:

```sh
./bin/pi-ssh 'jarvis status'
./bin/pi-ssh 'tail -n 100 /home/<user>/jarvis/logs/jarvis_voice.log'
```

## 5. Configuration Reference

Defaults live in `config.py`. Repository assets and logs are resolved from the
checkout automatically. Settings can be overridden without editing code by
using environment variables.

- Microphone input device: `AUDIO_DEVICE = "default"` with fallbacks for `pulse`, `a USB audio device`, and index `0`.
- Playback backend: automatic (`alsa` on Linux, `sounddevice` on Windows)
- Speaker playback device: a configured USB audio device on Linux and the system default elsewhere
- Linux ALSA volume card/control: the configured card/control, volume `85%`
- Wake words/phrases: `hello jarvis`, `hey jarvis`, `hi jarvis`, `hello computer`, `hey computer`, `jarvis`, `computer`, `hello`. Standalone `hey` and `hi` does not wake Jarvis.
- Lenient wake level: `0` (exact phrases only). Higher values allow fuzzy matches; `100` wakes on any recognized speech.
- Command speech-to-text engine: `whisper`; Vosk is still used for wake detection.
- Whisper model: `../whisper.cpp/models/ggml-tiny.en.bin`, relative to the checkout
- Wake response: `Hi. How can I help?`
- Initial command listen window: `60` seconds, with an earlier stop after speech followed by a short silence.
- Follow-up listen window after an answer: `4` seconds.
- Agent API: `http://<PI_LAN_IP>:1235/v1/agents/jarvis`
- Command center: `http://<PI_LAN_IP>:8765` on the deployed Jarvis Pi.
- Vosk model: `runtime/assets/vosk-model-small-en-us-0.15`
- Piper voice model: `runtime/assets/piper/en_US-amy-medium.onnx`

Common environment overrides:

- `JARVIS_PROJECT_DIR`, `JARVIS_VENV_DIR`, `JARVIS_LOG_FILE`, `JARVIS_LOCK_FILE`
- `JARVIS_API_BASE_URL`, `JARVIS_API_URL`, `JARVIS_API_HEALTH_URL`, `JARVIS_API_MODEL`
- `JARVIS_AUDIO_DEVICE`, `JARVIS_AUDIO_DEVICE_FALLBACKS`
- `JARVIS_PLAYBACK_BACKEND` (`auto`, `alsa`, `sounddevice`, or `echomuse`), `JARVIS_PLAYBACK_DEVICE`
- `JARVIS_SPEAKER_PROFILES_PATH` (defaults to `speaker_profiles.json` in the checkout)
- `JARVIS_CONFIGURE_VOLUME`, `JARVIS_VOLUME_CARD`, `JARVIS_VOLUME_CONTROL`, `JARVIS_VOLUME_LEVEL`
- `JARVIS_COMMAND_STT_ENGINE` (`whisper` or `vosk`)
- `JARVIS_COMMAND_AUDIO_RMS_THRESHOLD` (positive integer, default `420`;
  controls speech detection in Whisper recording)
- `JARVIS_COMMAND_SILENCE_SECONDS` (default `2.0`, greater than 0 and at most
  10; silence after speech before ending the Whisper recording. Shorter values
  reduce delay but may split a question at a natural pause.)
- `JARVIS_WHISPER_CPP_DIR`, `JARVIS_WHISPER_CPP_BINARY`, `JARVIS_WHISPER_MODEL_PATH`
- `JARVIS_VOSK_MODEL_PATH`, `JARVIS_PIPER_MODEL_PATH`, `JARVIS_PIPER_BINARY`
- `JARVIS_PIPER_BACKEND` (`cli` by default; `python` reuses a loaded Piper
  voice inside Jarvis instead of starting a subprocess for each utterance)
- `JARVIS_PIPER_SENTENCE_SILENCE` (extra silence between sentences, default
  `0.25` seconds; range `0`–`2`; `0` disables the added gap)
- `JARVIS_WAKE_WORDS` (comma-separated phrases), `JARVIS_LENIENT_WAKE_LEVEL` (`0`–`100`)
- `JARVIS_COMMAND_RECORDING_PATH`, `JARVIS_REPLY_WAV_PATH`

## 6. Notes

See [EXPERIMENTS.md](EXPERIMENTS.md) for the deployed voice pipeline, numbered
trials, user feedback, and the short comparison procedure.

Voice events include millisecond timestamps. `spoken` records the response text
before synthesis; `speech_audio_ready` reports synthesis time,
`speaker_audio_sent` marks the first PCM packet sent to EchoMuse, and
`speech_output_finished` reports playback-call and total output time.
The first packet is not a measurement of audible sound: EchoMuse buffers audio,
and the playback call includes an estimated drain wait.

For the reusable-voice trial, set `JARVIS_PIPER_BACKEND=python` and restart.

It uses the installed `piper-tts` Python API and `JARVIS_PIPER_MODEL_PATH`;
the first utterance loads the model, and later utterances reuse it.
`JARVIS_PIPER_BINARY` applies to the `cli` backend. Set the backend back to
`cli` and restart to restore subprocess synthesis.

Both Piper backends add `JARVIS_PIPER_SENTENCE_SILENCE` between the sentences
identified by Piper, with no added silence before the first or after the last.
This gap is separate from speaking speed and adds to any pause generated by
the voice itself. Set it to `0` for the previous timing, or adjust it and restart
Jarvis. The Python backend still reuses its loaded voice.

Speech cleanup preserves contractions (including curly apostrophes), commas,
periods, semicolons, and colons such as the one in `3:30`. Typographic clause
dashes become commas, and numeric ranges such as `30–45` become “30 to 45.”
For example, `I’m good—ready when you are.` is spoken from
`I'm good, ready when you are.` The API can return ordinary punctuated text;
pause timing is handled locally, without changing the response's wording.

Set `JARVIS_WAITING_ANNOUNCEMENTS=false` to suppress “Checking” messages while
the API is working. The default is `true`. Disabling these announcements avoids
waiting for their playback when the answer arrives during an announcement.

Jarvis uses Vosk for wake detection and local `whisper.cpp` for command transcription.

For a larger Vosk recognition-model trial, download
[`vosk-model-en-us-0.22-lgraph`](https://alphacephei.com/vosk/models)
and extract its model directory into `runtime/cache` (about 204 MiB extracted).
Set `JARVIS_VOSK_MODEL_PATH=runtime/cache/vosk-model-en-us-0.22-lgraph`
in the Pi's `.env`, then run `jarvis restart`. This changes the recognition
model without restricting its vocabulary or changing the wake phrases.
Compare the `[Vosk] Heard:` lines against the same spoken sentences.
To revert, remove that override (or restore its previous value) and restart.
The bundled `runtime/assets/vosk-model-small-en-us-0.15` remains the default.

Command recording continues until the configured silence interval or listening
deadline. Vosk quick-command candidates (such as “nothing” or “stop”) cannot
end recording or bypass Whisper. The full Whisper transcript determines the
command, including whether to end the session. Logs show
`quick_command_candidate` and `quick_command_verified` when a candidate is
available; partial Vosk guesses are ignored.

The `tiny.en` Whisper model is the smallest practical local Whisper model for this Pi. It is good for testing, but command transcription may still be slower than Vosk because Whisper records the whole command audio clip first, then transcribes it.

Windows uses PortAudio playback through `sounddevice`; Linux keeps the existing
ALSA `aplay` path. The PowerShell launcher selects Vosk so Windows does not
require a separate `whisper.cpp` build for local testing.

Jarvis validates that the chosen microphone supports the configured `SAMPLE_RATE` before opening it. If the USB microphone or speaker appears under a different card/device number, update `AUDIO_DEVICE`, `AUDIO_DEVICE_FALLBACKS`, `PLAYBACK_DEVICE`, `VOLUME_CARD`, and `VOLUME_CONTROL`.

### Saved Raspberry Pi speaker profiles

`speaker_profiles.json` stores an ordered list of known speakers and stays local.
Copy `speaker_profiles.example.json` to that path, then replace the example
Bluetooth address and USB identity with your own hardware values.
Its USB identity includes its serial number; detection resolves the current ALSA
card ID on every playback, so changing card numbers does not lose the speaker.
The saved hardware rates are informational; `plughw` converts speech to the
speaker's supported format.

To enable profile selection on the Pi, set this in its `.env` and restart Jarvis:

```bash
JARVIS_PLAYBACK_DEVICE=profiles
```

Jarvis tries connected profiles in file order, moving to the next if playback
fails, then tries ALSA `default`. Disconnected profiles are skipped. An unknown
speaker is not added automatically: inspect and test it, then append a USB
profile with its `/dev/snd/by-id` link name, playback device number and mixer
settings, or a Bluetooth profile with `backend: "bluetooth"` and its
`bluetooth_address`.
Use this read-only command to list saved profiles and their connection state:

```bash
runtime/venv/bin/python speaker_profiles.py
```

An Echo can alternatively act as a Bluetooth output-only speaker. Pair your
own device and record its address in the local speaker profile. Power it with
its original wall adapter.
It requires a connected Bluetooth audio sink in the Pi user's PipeWire/PulseAudio
session, with `pactl` for detection and `paplay` for playback. The resolver matches
the Bluetooth address even if the sink's numeric suffix changes. A disconnected
Echo is skipped; selection does not initiate pairing or reconnect it.

For an already paired Echo, reconnect with:

```bash
bluetoothctl connect <SPEAKER_BLUETOOTH_ADDRESS>
```

When both are connected, the Echo is tried first; P10S is the backup if the
Echo is absent or playback fails. Bluetooth volume stays at its current setting. Bluetooth
playback uses the Echo as an output speaker only: keep a microphone attached to
the Pi for the existing Jarvis wake words. The Echo's own Alexa wake word is
separate from Jarvis.

USB profile volume uses the resolved card and saved control/level. Explicit
`JARVIS_VOLUME_*` overrides still take priority; `JARVIS_CONFIGURE_VOLUME=false`
disables mixer changes. With no opt-in, Linux keeps `plughw:2,0` and its existing
fallback. Windows/PortAudio and local launchers keep their existing behavior;
`profiles` is only an ALSA playback setting. Microphone selection is independent.

### Echo Dot microphone and speaker over Wi-Fi

A rooted Echo Dot 2 running [EchoMuse](https://github.com/wilbowes/EchoMuse)
v2.18.1 can provide both audio input and output to the existing Jarvis loop.
The Pi continues to perform wake-word detection, transcription, agent calls,
and speech synthesis. No Home Assistant controller is needed for this adapter.
The Echo uses its wall adapter and Wi-Fi during normal operation; USB is used
for provisioning and recovery. Stock Alexa firmware does not expose this audio
interface.

Install the locked dependencies, then set these variables in the Pi's `.env`:

```bash
JARVIS_AUDIO_DEVICE=echomuse
JARVIS_PLAYBACK_BACKEND=echomuse
JARVIS_ECHO_BIND=<Pi LAN address>
JARVIS_ECHO_PORT=8766
JARVIS_ECHO_DEVICE_ID=<Echo serial number>
JARVIS_ECHO_TOKEN=<random secret of at least 32 characters>
```

The listener defaults to localhost unless explicitly configured. It accepts
only the configured device and shared token, on `/control` and `/data`; it
does not expose EchoMuse's remote shell. This adapter uses plain WebSockets
on the trusted LAN, so do not expose its port to the internet. Audio is
streamed to the Pi while Jarvis is listening, including for its wake word.
The Echo's microphone-mute button remains effective.

The ring turns cyan when Jarvis accepts a wake phrase, stays lit during the
conversation, and switches off when Jarvis returns to waiting for a wake word.
The current ring state is restored after a Wi-Fi reconnect. The device still
controls its red mute indicator, volume display, and orange disconnected light.
Light-control failures do not interrupt voice processing.

Wake detection uses the centre microphone. When a wake phrase is accepted,
Jarvis asks EchoMuse to select a directional microphone from the array and keeps
that selection through the greeting, command, response, and follow-ups. The mic
stream stays running between these stages so the direction is not lost; audio
is discarded when no recognizer is consuming it. Returning to idle releases the
selection. This is directional mic selection, not Amazon's original array
processing. Vosk still detects the wake phrase and Whisper transcribes commands.

For reliable **Hey Jarvis** detection independently of Vosk's transcript, install
EchoMuse's on-device openWakeWord assets in `/data/local/share/echomuse/oww` on
the Dot: `libonnxruntime.so` (Android ARMv7 ONNX Runtime 1.19.2),
`melspectrogram.onnx`, `embedding_model.onnx`, and `hey_jarvis_v0.1.onnx`
(openWakeWord v0.5.1 model release). Follow
[EchoMuse's asset installation instructions](https://github.com/wilbowes/EchoMuse).
Then set `JARVIS_ECHO_NATIVE_WAKE=true` on the Pi and restart Jarvis.
`JARVIS_ECHO_WAKE_THRESHOLD` defaults to `0.5`; higher values are stricter.
The Dot detects the phrase acoustically and reports it over the authenticated
control connection. Jarvis accepts only fresh detections while a microphone
consumer is active. Its existing exact Vosk phrases remain available.
This mode requires those assets; verify the Echo log reports
`on-device wake word scoring` with the `hey_jarvis_v0.1` model after startup.
In the Jarvis log, `[Vosk] Heard partial:` and `[Vosk] Heard:` identify
transcripts. `wake_detection_received detector='openwakeword'` records an
Echo detection with its model, score, age, threshold, and result (`queued`,
`below_threshold`, `stale`, `muted`, or `no_listener`). Queued means available
to the wake monitor; `wake_heard` identifies the detector Jarvis actually
accepted. `wake_detection_ignored` explains duplicate or expired detections.
These are detection events, not continuous openWakeWord scores or transcripts;
silence in this log does not prove the Echo detector is running.
The adapter keeps audio streaming to the Pi for transcription; this is not
EchoMuse's private-listening mode. Physical microphone mute still takes priority.

Provision the same token into `/data/local/etc/echomuse/token` on the Echo,
with root ownership and permissions `600`. Set
`/data/local/etc/echomuse/controller.json` to:

```json
{"endpoints":[{"host":"<Pi LAN address>","port":8766}],"mdns":false}
```

Use EchoMuse's documented startup script and boot service for the device.
Restart Jarvis after configuring both ends. The adapter reconnects after
network interruptions and resumes the current microphone listener. It
preserves the physical volume buttons and supports wake-word interruption
of responses. The network audio format is mono PCM16: 16 kHz microphone
input and 48 kHz speaker output.

To return Jarvis to the saved USB/Bluetooth speaker profiles, restore its
previous `JARVIS_AUDIO_DEVICE`, set `JARVIS_PLAYBACK_BACKEND=auto`, and keep
`JARVIS_PLAYBACK_DEVICE=profiles`. The saved P10S profile remains available.
The Bluetooth Echo profile requires restoring the Echo's stock software.

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
answers, that command goes through the usual command capture, Passer API, reply,
and follow-up loop. If the user stays silent, Jarvis naturally returns to wake
listening.

To let Home Assistant call it over the LAN, set `JARVIS_COMMAND_SERVER_TOKEN`.
When a token is configured and `JARVIS_COMMAND_SERVER_HOST` is not set, Jarvis
listens on `0.0.0.0:8765`. Without a token, it stays on localhost. You can set
`JARVIS_COMMAND_SERVER_HOST` explicitly to override either default. Send the
token as either `Authorization: Bearer <token>` or `X-Jarvis-Token: <token>`.

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

The simulator converts scripted utterances to WAV, transcribes them through the
configured speech-to-text engine, synthesizes each spoken reply with Piper, and
waits for the generated WAV duration without playing through the speaker. It
still runs through wake matching, wake reply selection, command cleanup, normal
command handling, reply handling, follow-up timeout behavior, and voice-event
logs. Timing delays, fake replies, and JSON summaries are suite data, not
command-line modes.
If Piper, `whisper.cpp`, or the configured Vosk runtime is unavailable, the
simulation fails at that audio step; there is no text-only fallback path.

## 9. Log Examples

Expected startup output includes:

```text
Loading Vosk model...
Jarvis voice loop running.
Say one of these to wake: hello jarvis, hey jarvis, hi jarvis, hello computer, hey computer, jarvis, computer, hello
Lenient wake level: 0
Press Ctrl+C to stop.
Waiting for wake word...
```

The log includes what speech recognition heard, what was sent to the Passer API, and what came back:

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
Whisper command recording detected speech after 1.0s (rms=456).
Stopped recording after 4.2s: speech followed by 1.2s silence; saved /path/to/pi-jarvis/logs/command.wav (peak rms=4567).
Whisper transcribing /path/to/pi-jarvis/logs/command.wav...
Whisper transcript after 3.3s: 'what is the weather today'
Command: what is the weather today
```

## 10. Project Layout

- `jarvis_voice.py` - main entry point.
- `config.py` - audio devices, wake words, API URL, command center settings, model paths, timing, and spoken phrases.
- `conversation_loop.py` - wake/listen/ask/speak loop.
- `jarvis_command_server.py` - local HTTP command endpoint for Home Assistant.
- `listen_to_mic.py` - microphone stream using `sounddevice`.
- `speech_to_text.py` and `detect_wake_word.py` - Vosk speech recognition and wake-word detection.
- `call_agent_api.py` - HTTP calls to the Jarvis/Passer agent API.
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
- If Whisper records silence even when you speak, lower `JARVIS_COMMAND_AUDIO_RMS_THRESHOLD`; if it records background noise as speech, raise it.
- If TTS fails, confirm `piper` is installed and `PIPER_MODEL_PATH` points to the `.onnx` voice model.
- If Jarvis cannot hear commands, use the platform-specific `sounddevice` command above and update `AUDIO_DEVICE`.
- If audio plays through the wrong speaker on Linux, run `aplay -l` and update `PLAYBACK_DEVICE`. On Windows, use the `sounddevice` command above and set `JARVIS_PLAYBACK_DEVICE` to the desired name or index.
- If Windows blocks the PowerShell launcher, allow scripts only for the current shell with `Set-ExecutionPolicy -Scope Process Bypass`, then run `.\run_local.ps1` again.
- Windows x64 is supported by the locked native packages; Windows ARM and 32-bit Windows are not currently validated.
- If LAN clients cannot reach Jarvis, confirm they are using the deployed Pi address and command-center port, for example `http://<PI_LAN_IP>:8765`.

## Experimental direct echo-dot-assist connection (E12)

`hassmic_jarvis.py` connects the Echo's Wyoming satellite directly to local
Whisper, the existing Jarvis API/conversation ID, and the configured Piper voice.
Home Assistant is not required by this experimental path. It is separate from
`jarvis_voice.py`. Setting `JARVIS_HASSMIC_HOST` selects it in the normal Pi launcher.

The Echo must run compatible stock firmware and a **rebuilt** `hassmic` containing
[patches/echo-dot-assist-jarvis-followup.patch](patches/echo-dot-assist-jarvis-followup.patch).
Also apply [patches/echo-dot-assist-playback-drain.patch](patches/echo-dot-assist-playback-drain.patch) so playback completion waits for the mixer queue.
The patches target upstream commit `a4fe0bdb6ac6914b1a02cda9f4a1a4f4ace94750`.
It adds a capability flag and a playback-end request to restart listening. The
unmodified signed upstream binary does **not** contain this patch. The connector
rejects that binary rather than silently dropping follow-ups. Set the Echo to
Wyoming mode with local wake detection; the initial stock wake may be Alexa.

After firmware compatibility, backup/recovery, patch build and device deployment
are completed, run on Linux/Pi:

```bash
jarvis stop
JARVIS_HASSMIC_HOST=<Echo-LAN-address> ./run_hassmic.sh
```

This foreground launcher reads `.env`, preserves caller `JARVIS_*` overrides,
and shares the ordinary Jarvis lock. `JARVIS_HASSMIC_PORT` defaults to `16700`.
Select Whisper, Pasture (backend server), and the desired Piper model in `.env`. It waits for the on-device wake,
captures mono 16 kHz speech, transcribes, asks the agent, sends the response WAV,
waits for `played`, and opens a follow-up listening window. If speech does not
begin, the current Pi configuration returns quietly to wake standby after
**7 seconds**, both after the
wake word and after an answer. Set `JARVIS_HASSMIC_WAKE_WAIT_SECONDS` and
`JARVIS_HASSMIC_FOLLOWUP_WAIT_SECONDS` to override those waits (each defaults to
5 seconds; allowed range greater than 0 through 60). Once speech starts, the
existing total capture limits remain 25 seconds initially and 20 seconds for a
follow-up. `JARVIS_COMMAND_SILENCE_SECONDS` still controls the pause after speech;
the current Pi setting remains **1.5 seconds**. A spoken end-session command
resets the existing agent conversation. No initial synthesized greeting delays
command capture. Idle wake listening has no timeout. Speech must exceed the
configured RMS threshold for 120ms before endpoint detection starts. The current
trial disables the Echo chime with `-E`. For normal `jarvis start`, `restart`,
and `logs`, set `JARVIS_HASSMIC_HOST=<Echo-LAN-address>` in the Pi `.env`.
With that setting, `run_jarvis.sh` selects the satellite controller and writes to
`logs/jarvis_voice.log`; without it, the existing runtime stays the default.
`jarvis logs` reports `wake_listen_started` on entering wake standby and
`wake_heard` when the Echo starts a new command capture, followed by speech and
Whisper transcript events. Follow-up capture is not counted as a new wake.
The Echo runs a keyword model, not continuous transcription: words spoken while
waiting for a wake are not available in the Pi log. The Echo's own detector log
contains the detected keyword and score; the current Wyoming protocol does not
forward these accurately, so the Pi does not invent them.

Voice controls are handled locally after transcription. **Stop**, **cancel**,
**goodbye**, **never mind**, **stop listening**, **stop talking**, **stop
responding**, **be quiet**, **quiet**, **silence**, **shut up**, **that's enough**,
and **end the conversation** end the current conversation without an agent
reply or another follow-up recording. Wake listening remains available for a
new request. You can include a wake name or “please,” such as “Computer, stop
listening” or “Please be quiet, Jarvis.” Matching requires a complete control
phrase; requests such as “stop the music” still go to the agent.

**Stand down** also pauses on-Echo wake handling for one hour by default
(`JARVIS_STAND_DOWN_SECONDS`, in seconds). It acknowledges once without opening
a follow-up window, sends `pause-satellite`, and queues announcements until
the pause ends. The pause survives Echo reconnections within the running Pi
process. At expiry, wake handling resumes automatically; `jarvis restart`
clears the in-memory pause early. This is a software listening pause; the
Echo's physical mute button remains the hardware microphone control.

When updating `bin/jarvis`, refresh an installed copy too:
`sudo install -m 755 bin/jarvis /usr/local/bin/jarvis`.
This changes Pi command routing, not the Echo's boot service.

The controller also starts the existing authenticated command server on port
8765 when enabled. Announcements queue until the Echo is idle, play through
Wyoming, and open the normal follow-up window. `command_server_instruction_finished`
means the Echo acknowledged playback; an HTTP success only means queued.
Connection or processing failures trigger a reconnect after five seconds while
the receive API stays available. Queued announcements survive reconnects, but
not process restarts; an announcement whose playback fails is logged and is not
automatically replayed because it may already have been heard.

The E12 trial migrated one Dot 2 and completed three-turn acoustic tests with
Alexa and Hey Jarvis; occasional transcription errors remain. The Echo now has a persistent startup service: on power-up it runs the custom
satellite and joins its saved Wi-Fi. The Pi controller uses TCP keepalive
(15-second idle, 5-second interval, three probes on Linux) to detect power loss
and reconnect. Use a suitable wall adapter and remain within Wi-Fi coverage.
Interruption during agent work and slow-response recovery are not yet validated.
Wyoming is unencrypted: use only
a trusted LAN. Do not run both controllers against the same microphone.
See [E12-ECHO-DOT-ASSIST.md](E12-ECHO-DOT-ASSIST.md) for the observed firmware
migration evidence, trial observations, and remaining limitations.


Pi restart/logging: the launchers use `flock -F` so the Python runtime itself
holds the single-instance lock. `jarvis stop` handles both legacy and satellite
processes. On a new start, the previous log is retained under `logs/archive/`;
`jarvis logs` follows the current log across restarts. A failed start returns a
nonzero exit code and prints its captured startup output. `jarvis status` also
returns nonzero when stopped.

Current wake-word trial (E15): the Echo runs **Hey Jarvis** plus **Computer**
locally in microWakeWord's two slots. Hey Jarvis is the published ESPHome v2
model (Kevin Ahrendt, cutoff 0.97); Computer is the community v2 model from
[JohnnyPrimus/Custom_V2_MicroWakeWords](https://github.com/JohnnyPrimus/Custom_V2_MicroWakeWords/blob/main/models/computer/computer.json)
(Leland Olney, cutoff 0.66). These are pretrained detectors, not personal voice
enrollment. Alexa is not enabled. The second model was initially added to the temporary satellite. The later
personalized models and persistent installation supersede this E15 configuration. Speaker playback tests send
real audio through the P10S and do not send a programmatic wake trigger. Compare
live-voice and speaker tests at the same physical placement before tuning.

### Primary-user voice setup (collection stage)

The October 22 manual four-position room session uses a separate guided helper
at `runtime/cache/manual-recording/session_today.py` on the Pi. Its revised
prompts record **Hey Jarvis**, **Computer**, and **Jarvis** for eight seconds
each, with two repetitions per phrase. Each ordinary sentence gets its own
fourteen-second recording, also with two repetitions. Initial preparation and
movement gaps are ten seconds. The four positions are living room near/far and
kitchen near/farthest, with the Echo kept fixed. Each position also includes
four seconds of background sound: 24 clips total. The manual helper is
date-restricted to October 22 and keeps an explicit session allowlist for later
training; it does not train or activate models. Earlier completed recordings
retain their original durations and labels. This manual flow is separate from
the voice-triggered setup below.

With the direct Echo controller, wake it and say **“do setup”** or **“start voice
setup”**. This is handled locally, before the Jarvis API. Follow the spoken
prompts at three positions: close, farther away, and off to one side. At each
position it records a quiet-room sample, two repetitions each of Computer and
Hey Jarvis, and two everyday phrases. Move when prompted and say “ready” within
15 seconds. Wake phrases record for eight seconds; the longer everyday phrases
record for fourteen seconds. Between samples, stay where you are until asked
to move to the next position. Say **“cancel setup”**
during a speaking step to stop. The full flow takes several minutes. Queued
announcements wait until setup finishes. Use the physical mute button if needed.

Audio and a JSON manifest are stored under `logs/voice_profiles/primary/<session>`
on the Pi (override with `JARVIS_VOICE_PROFILE_DIR`). Recordings are captured
without the normal speech threshold, so quiet examples are kept. Transcripts,
expected phrases, location labels, and audio-level measurements are saved for
review. Cancelled/interrupted sessions are retained but do not replace the last
completed session pointer. This is a single primary-user dataset, not speaker
identification. Normal questions are not automatically stored in this profile.

**This version collects data; it does not train models or apply calibration.**
Successful collection is marked `collected_needs_review`, not trained. Clips
contain two repetitions and need segmentation and label review. Whisper text
is not treated as a verified label. A separate test set and ordinary non-wake
speech/noise are needed to evaluate misses and false activations before replacing
models. Audio here is the Echo's processed command stream; compatibility with
its pre-wake detector input must be checked before using it for training.

If an interactive terminal uses `~/.local/bin/jarvis`, update that copy too:
`install -m 755 bin/jarvis ~/.local/bin/jarvis`. Check `type -a jarvis` in that
terminal for precedence. `jarvis logs [lines]` shows 80 recent lines by default
and follows the filename across restarts (`tail -F`). Reopen an already-running
old `tail -f` viewer once after upgrading the launcher.

Lifecycle commands (`start`, `stop`, `restart`) share a management lock and wait
up to 15 seconds for another lifecycle command to finish. This prevents two
terminals from stopping each other's newly started runtime. `status` and `logs`
remain available during that wait. The runtime does not inherit this lock.

### Wake-model startup evidence on the direct Echo connection

Every Jarvis startup or Echo reconnection logs one `wake_model_loaded` event per
successfully loaded microWakeWord model, with its name, slot, SHA256 fingerprint,
threshold, and smoothing window. Read these with `jarvis logs`. This requires the
Echo `patches/echo-dot-assist-model-status.patch`, applied after the follow-up
patch. The fingerprint is computed from the model bytes at load time, not from
files on the Pi or the protocol's legacy wake-word label. Missing/invalid reports
produce `wake_models_unverified`; connection alone does not prove model loading.
Restarting Jarvis reconnects to the Echo and reports its current loaded models;
it does not install or activate trained candidates.

Piper speaking speed can be adjusted with `JARVIS_PIPER_LENGTH_SCALE` in `.env`
(restart Jarvis afterwards). `1.08` makes speech approximately 8% longer than a
`1.0` setting, a slight slowdown; larger values are slower. Leaving it unset
preserves the model's default. Supported range is 0.5–3.0, for both Python and CLI
Piper backends on Linux and Windows.

### Streaming trial for the direct Echo connection

The existing Echo firmware already transports microphone and speaker audio in
chunks. To overlap transcription and speech preparation on the Pi, build the
optional server in your external `whisper.cpp` checkout:

```bash
cmake --build /path/to/whisper.cpp/build --target whisper-server -j 2
```

Place `whisper-server` beside the configured `whisper-cli` (Windows uses `.exe`).
Enable the trial in the Pi `.env` and run `jarvis restart`:

```dotenv
JARVIS_STREAMING_ENABLED=true
JARVIS_STREAMING_WHISPER_THREADS=4
JARVIS_STREAMING_STT_INTERVAL=1.0
```

The controller owns a loopback-only Whisper server, keeping the same model
loaded. It transcribes rolling snapshots while microphone audio arrives and
finalizes the latest snapshot after the existing end-of-speech pause. This is
incremental decoding with Whisper, not a native word-by-word acoustic model.
With incremental input disabled, only the finalized command goes to Pasture
(backend server). With it enabled, partial text can start planning as described
below; partial speech cannot run home actions. Four threads are appropriate for the tested four-core Pi; the default
remains the existing Whisper thread count unless explicitly overridden.

The Pasture agent API must support `stream: true` with the `pasture-voice-v1`
SSE protocol. Draft text can prepare up to two sentences of Piper audio early,
but only Pasture's validated `reply` is spoken. One continuous Echo playback
session delivers the reply sentence by sentence, preserving the configured
voice, pacing, and follow-up behavior. Tool progress is never spoken. The API
still receives one completed user message per turn. Older JSON-only servers
fall back using that same request; broken streams are never retried automatically.

`streaming_stt_ready`, `streaming_transcript_draft`, `streaming_transcript_final`,
`streaming_reply_committed`, and `streaming_first_audio_sent` appear in
`jarvis logs`. `hassmic_command.transcription_seconds` measures the remaining
transcription wait after capture. The first audio event marks network send,
not an independently measured audible start. Server diagnostics are in
`logs/whisper-stream-server.log`.

Rollback: set `JARVIS_STREAMING_ENABLED=false` and run `jarvis restart`. This
restores the original capture/Whisper/API/WAV flow; no Echo firmware or wake
models are changed. Native Windows hardware streaming is not validated.

### Incremental input to Pasture

With streaming enabled, `JARVIS_STREAMING_INPUT_ENABLED=true` also sends Whisper
transcript revisions to Pasture while the user is speaking. This requires the
updated Pasture API with `application/x-ndjson` input support. The default is
`false`; disable this flag alone to retain downstream streaming with the former
final-only request path.

One chunked HTTP request carries `start` metadata, revisable `partial` text, and
one `commit` containing the final cleaned transcript. Silence, local controls,
setup, errors, and cancellation close the provisional request without committing
an agent turn. A broken committed request is never retried automatically.

Pasture can begin its existing fast-triage planning call during speech. It may
reuse that work only when the final text, session, history, enabled skills,
work mode, active task frame, and agent configuration match. It runs at most two
provisional planning calls per utterance, with one in flight and only the newest
queued revision. Provisional work can consume model-call quota even if discarded.
Tools, home actions, conversation writes, and spoken replies wait for the final
commit. This is incremental text upload and early planning, not a model consuming
live audio or extending one already-running prompt with new words.

`streaming_input_partial_sent` proves that a revision left the Pi before
`streaming_input_committed`. `pasture_timing` reports planning/answer stages and
whether provisional work matched. A complete matching transcript arriving early
can hide some planning time behind speech; corrections and slow later tool/model
calls can still leave a noticeable delay. Wake models and sensitivity are unchanged.


### Echo device identities

`echo_devices.json` is a local, git-ignored inventory. Copy
`echo_devices.example.json` to that path and replace each example serial and
hostname with your own device details before enabling multi-device mode. Store
the matching identity on each Echo at `/data/local/hassmic/jarvis-identity.json`
and copy the inventory to the Pi. Serial numbers associate physical devices;
network addresses can change.

Enable multi-Echo mode on the Pi with:

```sh
JARVIS_ECHO_DEVICES_PATH=echo_devices.json
```

Put that setting in `.env`, then run `jarvis restart`. The existing launcher
selects the Echo controller when either this registry setting or
`JARVIS_HASSMIC_HOST` is configured. In registry mode, device endpoints come from
the registry; `JARVIS_HASSMIC_HOST` remains the single-Echo rollback setting.
Remove/unset `JARVIS_ECHO_DEVICES_PATH` and restart to return to the old mode.

The registry's `default_device_id` selects the recipient for existing untargeted
announcements. Each enabled entry has a unique `device_id`, `hardware_serial`,
`wyoming_host`/`wyoming_port`, and `conversation_id`. Missing conversation IDs
are derived as `<JARVIS_API_CONVERSATION_ID>-<device_id>`. Echo 1 explicitly keeps
`raspberry-pi-jarvis` to preserve its existing conversation. `room` is an optional
human-readable label. `enabled: false` keeps an entry out of the running fleet.
The registry is read at startup; restart after changes. It validates up to eight
entries; this limit is not a promise of eight-device Pi performance.

The two-device example uses Wyoming port 16700 and the `shared` listening
group, with a separate conversation ID for each Echo. Keep addresses stable
with DHCP reservations or update the inventory when addresses change.

To add another Echo, copy the structure of an existing entry and fill in its
actual serial and network address, use a new `device_id`, a different
conversation ID (or omit it for the derived ID), and the appropriate listening
group. Restore application/models from the backup only after checking hardware
compatibility. Give it its own `/data/local/hassmic/jarvis-identity.json`; do not
clone Echo 1's identity, network identity, or hardware-specific data. Serial
numbers are inventory associations, not an identity attestation by Wyoming.

Each Echo has its own connection, audio workspace, follow-up/stand-down state,
voice-setup directory, announcement queue, and reconnect loop. API requests carry
the per-device conversation ID plus `X-Pasture-Device-Id`; logs include
`device_id`. Resetting or standing down one Echo does not reset/pause another.
The Pi shares one loaded Whisper server, serializing inference to avoid model
contention, and one locked Piper voice. Independent conversations and playback
can overlap, but speech processing may queue and add latency under simultaneous
use. Voice setup recordings go under `logs/voice_profiles/<device_id>/primary/`.

#### Logs for both Echos

`jarvis logs` continues to show both Echos together, plus shared controller output,
in `logs/jarvis_voice.log`. Device events include `device_id='echo-1'` or
`device_id='echo-2'`. To follow only one device, use:

```bash
jarvis logs                 # Both Echos, last 80 lines and live updates
jarvis logs 200             # Both Echos, last 200 lines and live updates
jarvis logs echo-1          # Echo 1 only
jarvis logs echo-2 200      # Echo 2 only, last 200 lines and live updates
```

Each device also appends its structured voice events to
`logs/devices/<device_id>.log`: wakes, recognized commands, streaming timing,
reply events, announcements, connections and errors. Shared server output and
unstructured library diagnostics remain in the combined log. Separate device
logs persist across restarts and rotate at 5 MiB, keeping three older files
(`.log.1` through `.log.3`). Set positive `JARVIS_ECHO_LOG_MAX_BYTES` and
`JARVIS_ECHO_LOG_BACKUP_COUNT` in `.env` to adjust retention, then restart Jarvis.
These files contain spoken text; they are not continuous audio recordings.

#### Listening groups

`wake_group` defaults to `shared`. Echos that can hear the same person should
share a group: the first wake received owns the group until its conversation
returns to standby or its connection fails. Other group members reject wakes
while that conversation is active, preventing duplicate submissions. This is
first-arrival arbitration, not nearest-microphone selection. Devices in different
groups can handle simultaneous conversations independently. Use distinct room
groups only where that behavior is wanted; separate groups do not deduplicate
requests heard by both devices. Conversation handoff between rooms is not automatic.

#### Targeted announcements and broadcasts

The existing authenticated command endpoint remains on port 8765. POST to
`/command` with the existing token and one of these JSON bodies:

```json
{"text":"Dinner is ready.","device_id":"echo-1"}
{"text":"Dinner is ready.","device_ids":["echo-1","echo-2"]}
{"text":"Dinner is ready.","broadcast":true}
{"command":"status"}
```

Omit selectors to use `default_device_id`. Choose exactly one selector; unknown,
disabled or duplicate IDs fail without queueing any announcement. Broadcasts queue
on each device and play when it is idle; they are not sample-synchronized audio.
Status lists connection state, pending announcements and stand-down time for each
Echo. Existing Home Assistant alerts continue to use Echo 1 by default. Pasture
receives the separate conversation IDs; automatic per-device reminder routing in
Pasture requires it to supply the desired device selector to this command endpoint.

The deployed setup has two registered Echos. Tests exercise concurrent sessions
with virtual Wyoming peers; capacity beyond the two-device deployment has not
been established. The current seven-second
no-speech waits, 1.5-second end-of-speech pause and streaming paths are preserved.

#### Home Assistant arrival weather notes

The deployed Home Assistant household welcome waits ten seconds after entry and
targets Echo 1. Its weather-pattern logic runs in Home Assistant, separately from
the Pi runtime. Guest welcomes retain their greeting-only behavior and ten-second
delay.

`sensor.jarvis_welcome_weather_pattern` records Met.no's daily forecast condition
and high temperature every thirty minutes. It compares today with the previous
two calendar days, using dry 55–80°F days as pleasant, highs at or below 40°F as
cold, and highs at or above 85°F as hot. Rain/snow and storm conditions have their
own categories. A change after two similar days gets one brief household welcome
note that day. Continuing cold, heat, or wet weather gets a reminder at most once
every three days; continuing pleasant weather stays quiet.

`input_datetime.jarvis_weather_last_welcome` shares the cooldown across household
members. It advances only when the Pi accepts the welcome into its queue. Daily
history and the cooldown persist across Home Assistant restarts. Missing or stale
weather data produces no ordinary weather note, and a new installation needs two
previous days of history. Existing severe-weather alerts retain priority. With
no relevant events, the welcome is just the greeting, without an all-clear report.

The Home Assistant configuration uses `jarvis_weather_pattern.yaml`, included
under `template:`, plus the helper above and `script.jarvis_welcome_home`. These
are Home Assistant configuration files, not settings in the Pi's `config.py`.
