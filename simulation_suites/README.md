# Conversation Simulation Suites

Each JSON file in this folder is a reusable scripted conversation for
`simulate_conversation.py`.

Run one with:

```bash
runtime/venv/bin/python simulate_conversation.py --suite simulation_suites/basic_wake_turn.json
```

Current suites:

- `basic_wake_turn.json` - wake once and ask one command.
- `weather_followup.json` - wake with "hi", ask weather, then ask about rain.
  This suite sets `real_api: true`, so it calls the configured Jarvis/Pasture
  API in the Pi environment.

Required field:

- `utterances`: first item is the wake phrase, later items are the command and
  follow-ups.

Optional fields match the simulator flags:

- `real_api`
- `audio_mode`: `muted`, `synthesize`, or `play`
- `fake_reply`
- `fake_continue_listening`
- `fake_api_latency`
- `wake_delay`
- `command_delay`
- `followup_delay`
- `idle_followup_delay`
- `speak_audio`
- `summary_json`

Use `audio_mode: "synthesize"` to run Piper/TTS while skipping speaker playback.
Keep `audio_mode` away from `play` unless you intentionally want sound.
