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
sudo apt install -y alsa-utils portaudio19-dev
```

The project expects the Piper executable to be available as `piper`:

```sh
piper --help
```

## Configuration

Edit `config.py` if your Pi hardware or API host changes.

Current defaults:

- Microphone input device: `AUDIO_DEVICE = 2`
- Speaker playback device: `PLAYBACK_DEVICE = "plughw:2,0"`
- ALSA volume card/control in `play_audio.py`: card `2`, control `PCM`, volume `85%`
- Wake words/phrases: `hello jarvis`, `hey jarvis`, `hello computer`, `hey computer`, `jarvis`, `computer`, `hello`
- Initial command listen window: `60` seconds, with an earlier stop after speech followed by a short silence.
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

If the USB microphone or speaker appears under a different card/device number, update `AUDIO_DEVICE`, `PLAYBACK_DEVICE`, `VOLUME_CARD`, and `VOLUME_CONTROL`.

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
Press Ctrl+C to stop.
```

Say one of the configured wake words or phrases, wait for the prompt, then speak a command. Press `Ctrl+C` to stop.

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
- If TTS fails, confirm `piper` is installed and `PIPER_MODEL_PATH` points to the `.onnx` voice model.
- If the Pi cannot hear commands, run `python -m sounddevice` and update `AUDIO_DEVICE`.
- If audio plays through the wrong speaker, run `aplay -l` and update `PLAYBACK_DEVICE`.
- If the assistant says it cannot reach Pasture, confirm the API host is online and reachable from the Pi.
