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
- `indoor_outdoor_temperature.json` - wake with "hi", then ask for the current
  indoor and outdoor temperature through the local Jarvis responder.

Required field:

- `utterances`: first item is the wake phrase, later items are the command and
  follow-ups.

Optional fields:

- `fake_reply`
- `fake_continue_listening`
- `fake_response_latency`
- `wake_delay`
- `command_delay`
- `followup_delay`
- `idle_followup_delay`
- `summary_json`

The simulator always synthesizes scripted input to WAV, transcribes that audio
through the configured speech-to-text engine, synthesizes replies to WAV, and
waits for the reply audio duration without sending sound to the speaker.
