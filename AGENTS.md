# Repository instructions for coding agents

These instructions apply to the whole repository. `README.md` is the source of
truth for user-facing installation, launch, configuration, and hardware setup.

## Project shape

Pi Jarvis is a Python voice-assistant runtime. The main flow is:

1. `jarvis_voice.py` initializes the runtime.
2. Vosk listens for a configured wake phrase.
3. `speech_to_text.py` transcribes the command with Whisper or Vosk.
4. `call_agent_api.py` sends the command to the configured Jarvis/Passer API.
5. Piper synthesizes the response and `play_audio.py` plays it.

Keep hardware and service boundaries clear. Microphone input, speaker output,
Piper, `whisper.cpp`, and the Jarvis/Passer API may be unavailable during
development.

## Environment and dependencies

- Use `uv` with Python 3.12 as the development default and the repository-local
  `runtime/venv` environment.
- Preserve the declared Python 3.10 through 3.14 range. In particular, the
  complementary ONNX Runtime markers in `pyproject.toml` retain a compatible
  wheel for Python 3.10 on Raspberry Pi ARM64; do not remove or narrow them
  without checking the supported platform matrix.
- Never install project dependencies into the global/system Python.
- On Linux or Raspberry Pi, install/sync with:

  ```sh
  UV_PROJECT_ENVIRONMENT=runtime/venv uv sync --python 3.12 --locked
  ```

- On Windows PowerShell, install/sync with:

  ```powershell
  $env:UV_PROJECT_ENVIRONMENT = "runtime/venv"
  uv sync --python 3.12 --locked
  ```

- Use the interpreter inside `runtime/venv` for every project command. Do not
  rely on an activated environment or a bare `python`/`pip` command.
- When dependencies change, update both `pyproject.toml` and `uv.lock`. Otherwise
  keep `uv.lock` unchanged and use `--locked` or `uv lock --check`.
- `whisper.cpp` is an optional external checkout and must not be vendored into
  this repository. The tracked speech-model assets under `runtime/assets` are
  required runtime data and must not be removed or replaced unless explicitly
  requested. Generated `runtime/venv`, `runtime/cache`, and `logs` content must
  remain untracked.

## Platform contracts

- Raspberry Pi production behavior is the compatibility baseline. By default,
  command transcription uses `whisper.cpp`, playback resolves to ALSA device
  `plughw:2,0`, volume uses `amixer`, and `run_jarvis.sh` uses `flock` and file
  logging. Do not silently replace these defaults while making local-development
  changes.
- `run_local.sh` is the Linux development profile. It selects Vosk, the default
  audio device, foreground execution, and disables Pi-specific mixer changes.
- `run_local.ps1` is the native 64-bit Windows profile. Keep it independent of
  Bash, `flock`, ALSA, and POSIX-only paths/tools. Windows playback uses
  PortAudio via `sounddevice`, and executable discovery must support names such
  as `piper.exe`.
- Launchers must work from any current directory and must preserve caller-set
  `JARVIS_*` overrides.
- Resolve repository files from the checkout, preferably with `pathlib`; do not
  introduce machine-specific absolute paths into Python code.
- Put runtime settings in `config.py` and expose portable overrides with the
  `JARVIS_` prefix. Preserve existing environment-variable behavior.
- `config.py` reads environment variables at import time. Test configuration
  overrides in a fresh subprocess so another test's imported state cannot leak.
- Changes to microphone, playback, TTS, or subprocess code must consider both
  the Linux/ALSA path and the Windows/PortAudio path.

## Remote Raspberry Pi access

- For any request to inspect Jarvis on the Pi, check Jarvis logs, restart
  Jarvis, or run a remote test, use the repository wrapper:

  ```sh
  ./bin/pi-ssh 'jarvis status'
  ./bin/pi-ssh 'tail -n 100 /home/jarvis/jarvis/logs/jarvis_voice.log'
  ```

- In Codex, run `./bin/pi-ssh ...` with escalated network permissions on the
  first attempt. SSH to the Pi is a LAN network operation and the sandbox blocks
  it; do not first try an un-escalated SSH command and then recover.
- Do not invent SSH users, hosts, or IP addresses. The wrapper reads
  `RASPBERRY_PI_SSH` from `.env` and uses `.ssh_askpass` to read the password
  from the same file. In particular, do not assume the service IP is the SSH
  host.
- Do not pass `BatchMode=yes` for this project. It disables the required
  askpass/password flow and causes misleading `Permission denied` failures.
- When checking the command-center receive API from the Mac/LAN, use the Pi's
  configured LAN address: `http://<PI_LAN_IP>:8765/health`. Obtain that address
  from local configuration; do not publish it. SSH management still goes
  through `./bin/pi-ssh`.

## Validation

On Linux or Raspberry Pi, run:

```sh
runtime/venv/bin/python -m pytest
runtime/venv/bin/python self_test.py
uv lock --check
```

On Windows PowerShell, use:

```powershell
.\runtime\venv\Scripts\python.exe -m pytest
.\runtime\venv\Scripts\python.exe self_test.py
uv lock --check
```

When dependencies or the lockfile change, also verify resolution for Windows
x64 and the oldest supported Raspberry Pi/Python combination:

```sh
UV_PROJECT_ENVIRONMENT=runtime/venv uv sync --dry-run \
  --python 3.12 --python-platform x86_64-pc-windows-msvc --locked
UV_PROJECT_ENVIRONMENT=runtime/venv uv sync --dry-run \
  --python 3.10 --python-platform aarch64-manylinux2014 --locked
```

The test suite must mock microphone, speaker, and network boundaries. Keep
`self_test.py` safe to run without opening the microphone, playing audio, or
starting the command-center server or contacting the API. Add regression
coverage for every behavior change and for both platform branches when platform
dispatch is affected.

The full assistant loop waits for real microphone input and may contact a
private LAN API. Run it only as an intentional hardware/integration check. Do
not claim native Windows or Raspberry Pi hardware validation from Linux-only
unit tests or dependency resolution.

## Change hygiene

- Work on a feature branch rather than directly on `main`.
- Preserve unrelated user changes and do not rewrite existing history.
- Keep user-facing commands and prerequisites in `README.md`; update it when a
  change affects installation, launch behavior, configuration, or supported
  platforms.
- Before committing, run the applicable checks above plus `git diff --check`.
