# Echo setup: a custom voice satellite

This part of Pi Jarvis turns a supported Amazon Echo into a local voice satellite:
it detects a wake phrase, streams microphone audio to a controller, plays the
returned speech, and can listen again without another wake word. Two Echo Dot
2nd generation devices have been configured with this setup.

This document covers the **Echo itself**: firmware, root access, satellite
software, audio, wake models, boot behavior, and the network interface. The
[main README](../README.md) covers the controller and the rest of Pi Jarvis.

## What this project adds

The foundation is [echo-dot-assist](https://github.com/Gamer92000/echo-dot-assist)
and its `hassmic` satellite, using the Echo's existing audio hardware and
[microWakeWord](https://github.com/kahrendt/microWakeWord). This project builds
on that work with three published source patches:

| Contribution | Problem addressed | Result |
| --- | --- | --- |
| [Follow-up protocol extension](../patches/echo-dot-assist-jarvis-followup.patch) | The pinned Wyoming implementation lacked the controller-requested follow-up behavior needed here. | The Echo advertises the extension and can reopen listening after playback. |
| [Playback drain fix](../patches/echo-dot-assist-playback-drain.patch) | On the tested firmware, the mixer drain call returned before queued speech had finished. | Playback completion waits for the mixer queue, with a bounded timeout and cancellation handling. |
| [Loaded-model reporting](../patches/echo-dot-assist-model-status.patch) | A configured model name or file on disk did not prove which model was actually loaded. | The Echo reports successfully loaded model names, slots, SHA-256 fingerprints, thresholds, and smoothing windows. |

The device work also includes firmware migration, a custom cross-build,
persistent startup, personalized wake-model deployment, separate identities
for both devices, and checks of playback, follow-up listening, and reboot
recovery. The upstream audio front end, satellite foundation, and wake-word
engine are credited above; they were not created by this project.

## Hardware and software baseline

| Item | Configuration used |
| --- | --- |
| Hardware | Echo Dot 2nd generation, model RS03QR (`biscuit`) |
| Firmware | Fire OS 6574.1, NS65741/8146; product `biscuit_puffin` |
| Access | Rooted firmware with ADB access for installation and maintenance |
| Satellite | Custom `hassmic` build in Wyoming mode |
| Pinned upstream revision | `a4fe0bdb6ac6914b1a02cda9f4a1a4f4ace94750` |
| Upstream release used as the baseline | `v2026.10.19.193215-beta` |
| Build environment used | macOS with Android NDK 26.3.11579264, targeting `armv7a-linux-androideabi24` |
| Wake engine | microWakeWord on the Echo |
| Selected wake phrases | Personalized “Hey Jarvis” and “Computer” models |
| Transport | Wyoming over TCP, port 16700 |
| Command microphone audio | Mono, 16 kHz, signed 16-bit PCM |

These are the tested device and firmware combinations, not a compatibility claim
for every Echo. Hardware model, current firmware, and bootloader state matter.
Use the [pinned upstream device documentation](https://github.com/Gamer92000/echo-dot-assist/blob/a4fe0bdb6ac6914b1a02cda9f4a1a4f4ace94750/devices/biscuit/README.md)
when assessing another device.

## Device preparation and rooting

The original development device was migrated from an earlier rooted system to
the supported Fire OS baseline using the
[firebreak](https://github.com/bboe/firebreak) migration tooling. Root access and
the firmware's stock mixer libraries were verified before running the custom
satellite. The recorded firebreak revision was
`7c5e84142bb877d2d77c450027bfeaac8c7b645b`.

Preparation included private application and storage backups, checksum
verification, and recovery planning. A bootloader migration is not equivalent
to installing an application: having an application backup does not establish
a working firmware rollback path. Device images and recovery backups are not
published because they can contain credentials and device-specific data.

This is a record of the implemented setup, not a universal flashing script.
Follow the device-specific upstream prerequisites rather than applying these
firmware details to a different model.

## Microphones, audio processing, and speaker

`hassmic` uses the supported firmware's native audio front end and mixer. The
Echo retains its microphone processing, including echo cancellation and
beamforming; it is not reduced to an unprocessed USB microphone. The command
audio sent over Wyoming also comes through this audio path.

Wake detection and command capture are different stages. The Echo continuously
runs its local keyword detector while waiting for a wake. Once activated, it
streams command audio through the satellite connection. It does not continuously
transcribe everything said in the room.

For playback, the satellite accepts the audio format announced by the
controller and feeds PCM to the Echo's mixer. The drain patch keeps the mixer
open while queued audio finishes, then permits completion and follow-up
listening. Cancellation flushes pending audio instead. The deployed setup also
disables the wake chime to reduce interference with command capture.

## Wake-word training and installation

Training and inference are separate:

| Stage | Location | Output |
| --- | --- | --- |
| Prepare and train personalized wake models | Mac, outside this repository's runtime | Compatible model artifacts and metadata |
| Install and select the models | Echo | Local microWakeWord configuration |
| Detect “Hey Jarvis” or “Computer” | Echo | A wake event that starts the voice exchange |
| Inspect loaded-model evidence | Echo's Wyoming information response | Model names, fingerprints, and detector settings |

The deployed personalized models use microWakeWord-compatible TFLite artifacts.
Each Echo has its own installed copy. The current satellite build has **two
active model slots**; this is a software limit in this build, not a claim about
the Echo hardware's maximum capability.

Earlier trials used published pretrained wake models before the personalized
models were selected. Those historical selections and thresholds should not be
mistaken for the current personalized setup. Keyword detection also does not
prove who is speaking; it is not speaker authentication.

The training implementation, private recordings, and personalized model weights
are not distributed in this repository. The public artifacts here are the
integration patches and documentation. The repository's guided voice-collection
feature collects samples for review; it does not automatically train or install
a new model.

## Network interface and routing boundary

The Echo exposes a Wyoming TCP endpoint. A configured controller connects to
that endpoint; the Echo is not discovered by recognizing the brand of a speaker.
The connection carries control events and audio in both directions.

A typical exchange is:

1. The controller sends `describe`; the Echo returns `info`, including the
   custom `supports_jarvis_followup` capability and loaded-model report.
2. The Echo listens locally for a selected wake phrase. A detected wake starts
   the Wyoming pipeline exchange.
3. The Echo sends microphone audio as PCM chunks until capture is stopped.
4. The controller returns `audio-start`, `audio-chunk`, and `audio-stop` events
   for the Echo speaker.
5. If `audio-stop` includes `jarvis_followup: 1`, the patched Echo schedules
   listening to reopen after playback. Completion is reported through `played`.

This is the Echo's routing responsibility: expose its own microphone, wake
signals, and speaker through one network endpoint. Choosing between devices,
coordinating simultaneous wakes, and choosing announcement recipients are
controller responsibilities. The Echo does not contact Pasture (backend server)
directly in this setup.

Each installation has a distinct device label, such as `echo-1` or `echo-2`,
and its own `/data/local/hassmic/jarvis-identity.json` metadata file. The local
inventory associates that label with the physical device and its network
endpoint. Copying software or models to another Echo must not copy the first
device's identity or Wi-Fi/device-specific settings. Identity metadata is not
cryptographic authentication.

## Persistent startup and device services

The custom satellite is installed as a persistent boot service. On power-up,
the Echo joins its saved Wi-Fi network and starts `hassmic` in Wyoming mode.
The installation uses the upstream boot/main/system-install/lockdown scripts
with the custom binary and the required init-to-su SELinux transition.

The dedicated setup disables the stock Alexa voice service and Amazon update
services. This does not remove the stock audio libraries the satellite needs.
The physical microphone-mute button remains the device's hardware microphone
control. A Mac USB connection is used for maintenance, not required for normal
operation on the device's wall power supply.

## Build and installation boundaries

The patches are maintained in [`patches/`](../patches/) and target the pinned
upstream revision above. Apply the follow-up patch before the model-status
patch; the playback-drain patch changes the mixer module. A normal upstream
release binary does not contain these project-specific changes and must not be
represented as the custom build.

The recorded build also needed an assembler compatibility adjustment for the
newer macOS NDK. That build-only adjustment is not packaged as a complete
reproducible toolchain here. Upstream link stubs were used during compilation;
the real firmware libraries are required on the Echo, and link stubs must never
replace them. This folder does not ship firmware, a prebuilt satellite binary,
or a one-command installer.

For another device, the sequence is to confirm hardware/firmware compatibility,
prepare private backups and recovery, build the pinned source with the patches,
install and verify the satellite, install compatible wake models, assign a
unique identity, and test audio, follow-ups, mute, and reboot behavior. Detailed
migration observations remain in the
[historical development record](../E12-ECHO-DOT-ASSIST.md); earlier temporary
states in that record are not the final installed configuration.

## Verification and limitations

The development record includes real-device multi-turn speech trials,
confirmation of loaded personalized model fingerprints, and a reboot test in
which the satellite restarted and the controller reconnected. Host tests also
exercise follow-up ordering, playback drain, and model-status reporting:

- [Protocol and playback patch tests](../tests/test_hassmic_patch.py)
- [Model-status tests](../tests/test_echo_model_status.py)

Those tests do not establish a measured wake-word accuracy rate, robustness in
every room, or support for other Echo models. Reported playback acknowledgments
are software events, not independent measurements of when sound reached a
listener. The documented deployment contains two Echo devices.

Wyoming in this setup has **no transport encryption or satellite authentication**.
Use a trusted, restricted LAN and do not expose the endpoint to the Internet.
See [security boundaries](../SECURITY.md) for the distinction between this
connection and other interfaces. Credentials, addresses, serial numbers, voice
recordings, and device backups remain local; the public documentation uses
labels and placeholders.
