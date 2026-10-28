# E12: echo-dot-assist trial preparation

Status: persistent Echo startup installed with explicit user approval on 2026-10-21. Personalized wake models preserved. See the permanent-startup verification below; earlier temporary-install notes are historical.

## Pinned candidate

- Repository: https://github.com/Gamer92000/echo-dot-assist
- Commit: `a4fe0bdb6ac6914b1a02cda9f4a1a4f4ace94750`
- Release: `v2026.10.19.193215-beta`, confirmed to point to that commit.
- Source cache: `runtime/cache/echo-dot-assist/`
- Artifact: `runtime/cache/echo-dot-assist-artifacts/hassmic-biscuit.bundle`
- Signature verified with the pinned repository's release key and `otatool.py`;
  returned version `2026.10.19.193215`.

## Observed Echo compatibility

Read over USB ADB on 2026-10-20:

| Field | Current Echo | Candidate requires |
| --- | --- | --- |
| Device | biscuit / csm_biscuit | biscuit_puffin (RS03QR) |
| OS | Android 5.1.1, LVY48F | Fire OS 6574.1, NS65741 (Android 7.1.2) |
| Root | Magisk su works | Rooted supported stock firmware |
| Mixer | /system/bin/mixer and libmixerAPI.so absent | Stock mixer and matching libraries |
| ABI | arm64-v8a | Candidate's stock firmware uses 32-bit userspace |

This is not an app-only deployment on the current EchoMuse image. Firmware and
bootloader compatibility must be resolved before the candidate can run.
Upstream's biscuit instructions say amonet v2 upgrades bootloaders and older
Fire OS 5 will not boot afterwards. Do not call a firmware migration reversible
merely because an application backup exists.

## Backup completed

`logs/echo-dot-assist-E12-backup/echomuse.tar` (private, git-ignored) contains
EchoMuse settings, token, binaries and openWakeWord assets. All 15 archive
members were parsed; all regular file payloads were read and checked for length.
Archive size: 28,706,304 bytes. SHA-256:
`47f9aa0ede860773c11018d5de5d99e725f3ca0d4636918f81b5238cb16ab056`.
This is **not** a complete bootloader, partition or Wi-Fi backup. Do not publish
this archive: it contains the Echo authentication token.
The raw ADB stream is retained alongside it; a leading tar diagnostic was
removed to produce the validated archive. The local ADB reader was interrupted
after the complete archive had arrived but the connection remained open.

## Pipeline required for this trial

Use the experimental direct Wyoming connector described below: Echo audio and
wake events → local Whisper → existing Jarvis API → Piper Lessac → Echo playback.
Home Assistant is not part of this trial. The patched candidate adds the
follow-up capability missing from the upstream Wyoming implementation.

The upstream guided installer requires Linux, but the separately reviewed
firebreak project documents macOS and migration from the existing amonet v1
recovery. A cable move to the Pi is therefore not yet required. The Mac route
must be verified against this device before any writes.

## Next actions and comparison

1. Obtain and verify all migration prerequisites, including `boot-root.zip`,
   before migrating the Echo. Keep the direct Jarvis pipeline and Lessac.
2. Prepare a full recovery/partition backup and verify the firmware and
   bootloader migration path on an appropriate USB host. Review the concrete
   wipe/flash steps before performing the destructive change.
3. Use the matching stock firmware and validated candidate; start with the
   upstream foreground deployment if firmware compatibility permits.
4. Test stock Alexa wake separately from custom Hey Jarvis. Do not equate a
   successful Alexa wake with custom Jarvis accuracy.
5. Replay the same P10 questions and pause fixture; measure wake, capture, STT,
   response-ready to first output, and three follow-up questions after one wake.
6. Record observed results and any regression before selecting the new stack.

Sources:
- https://github.com/Gamer92000/echo-dot-assist/blob/main/devices/biscuit/README.md
- https://github.com/Gamer92000/echo-dot-assist/blob/main/docs/GUIDE.md#esphome-or-wyoming
- https://github.com/Gamer92000/echo-dot-assist/blob/main/scripts/setup.sh

## Updated choice: direct Jarvis controller, no Home Assistant

The user selected reuse of Whisper, the Jarvis agent and Lessac. Home Assistant
selection is no longer a prerequisite. The earlier ESPHome requirement applied
to the unmodified upstream stack; E12 now uses Wyoming plus an explicit upstream
follow-up extension.

Prepared `hassmic_jarvis.py`, opt-in `run_hassmic.sh`, and
`patches/echo-dot-assist-jarvis-followup.patch`. The connector checks the new
capability before starting. The patched satellite uses `core_restart_after()`
on the controller's audio-stop follow-up flag; the existing core restarts audio
capture after playback drains. The ordinary signed upstream bundle cannot be
used for this extension without a rebuild.

Validation includes an actual local socket pair with a simulated satellite,
three commands and replies, malformed/truncated frames, audio-format checking,
silent input, and refusal of an unpatched satellite. A host C harness applies
the patch to the pinned upstream module and verifies restart-before-playback-end
and unchanged behavior without the flag. These checks do not validate Echo ARM
execution, acoustic behavior, or firmware migration. Automatic reconnection,
barge-in during agent work, and long-running requests remain prototype limits.

## Build and staging result

The patched Echo executable was cross-built successfully using the already
installed Darwin Android NDK 26.3.11579264 for armv7a-linux-androideabi24.
A separate source copy under `runtime/cache/echo-dot-assist-jarvis/` contains
the follow-up patch and a build-only integrated-assembler adjustment needed by
this newer NDK. Stock-library stubs were used only for linking, as supported
upstream; **never install those stubs onto the Echo**. The real firmware's
libraries are required at runtime. This custom artifact is not the signed
upstream build, and binary equivalence is not claimed.

Executable: `runtime/cache/echo-dot-assist-jarvis/build/biscuit/hassmic`.
Build log and hash manifest: `logs/echo-dot-assist-E12-build/`.
No Echo execution or firmware flashing has happened.

Local suite: 161 passed, including host C patch harness. Pi suite: 160 passed,
one skipped (optional upstream checkout/C harness not present there). Pi smoke
test passed. The opt-in connector, launcher and configuration are staged on the
Pi; current EchoMuse runtime remains selected. The Echo is currently in TWRP
recovery for an offline storage backup, so voice input is unavailable.


## Migration preparation update (2026-10-20)

- Echo remains connected to the Mac in TWRP `3.7.0_9-bboe2`.
- All eMMC filesystems were confirmed unmounted before the read-only backup.
- Full eMMC (3,917,479,936 bytes), boot0 (1,048,576 bytes), and boot1
  (1,048,576 bytes) backups completed. Every image matched the checksum
  calculated on the Echo. Sizes and SHA-256 values are recorded in
  `logs/echo-dot-assist-E12-backup/partition-manifest.json`.
  Recovery default dd stopped short; resumed from the last full block using
  toybox dd, then verified the complete image against the device checksum.
- Fire OS NS65741 OTA downloaded and verified against SHA-256
  `90832e86498c5e803974c30359aea71c1129757be0ddc59d831a94b27f81487f`.
- Amonet v2 archive downloaded and verified against SHA-256
  `98297293701082bc7272efe077f941c56fc7b6e1f27ef6f2e93b6e4c6fc7b62d`.
- Inspected firebreak commit `7c5e84142bb877d2d77c450027bfeaac8c7b645b`.
  Its docs report an actual v1-bboe → v2 migration; the untested warning is
  specifically for the `--short` route and a different transitional state,
  not all v2 migrations. No firebreak migration has been executed here.
- User downloaded `boot-root.zip` after browser navigation was blocked.
  Verified size 473633 and SHA-256
  `de49cc88b27a8e77cf97cf0156bee50e4ddc0e116c41aaede06b494e38397be0`.
- No firmware writes or wipes performed. Raw disk images do not back up RPMB
  and do not by themselves prove a complete bootloader rollback procedure.


## Hardware results (2026-10-20, E12a–E12c)

Firmware migration completed on the Mac in 4m43s using the pinned firebreak
source: both slots run Fire OS 6574.1 (NS65741/8146), root adb verified, product
biscuit_puffin, stock libmixerAPI and libpryon present. Echo joined the supplied
Wi-Fi network at <ECHO_LAN_IP>. Credentials are held only in private ignored
files and the device Wi-Fi profile; do not publish backups.

The foreground upstream run.sh inherited its background avahi daemon into
hassmic. Amazon's attestation code waited on that child and never opened the
controller port. Terminating that specific child unblocked startup. Subsequent
trials launch runas directly, without inheriting avahi. This does not install
a boot service.

| Trial | Change | Observed result |
| --- | --- | --- |
| E12a | Stock Alexa wake, direct Wyoming follow-up patch | One wake, three API answers 4/7/14; “Add three” became “or three”. Mixer drain returned immediately (10–130ms completion); follow-up chime triggered speech and an empty transcript. Initial harness lacked the standby event. |
| E12b | Wait for mixer queue; disable chime | All three questions transcribed correctly, answers 4/7/14. Reply completion 0.35–0.66s after send. Residual short sound still caused an empty follow-up and early standby. |
| E12c | Hey Jarvis microWakeWord; require 120ms sustained speech | Wake accepted, three answers 4/7/14. “Add three” became “3 to that”; other questions correct. Final follow-up waited 19.97s then standby without unnecessary Whisper transcription. |

Whisper processing was 2.61–2.74s per command. API response received → PCM send
was 2.05–2.13s for the first (cold Piper) response, then 0.087–0.115s. These are
send timings, not independently measured acoustic first-sample latency.
A P10 microphone room recording captured the E12c trial; its separate Whisper
transcript contains “Seven” and “14”, but also noise labels and misses other
words. Do not claim it independently verified every spoken word.

Evidence: `logs/e12-hardware-results/` contains Echo logs, Pi controller log,
three result.json files, synthesized test fixtures, and the room recording.
The official Hey Jarvis v2 model/manifest are cached under runtime/cache/e12-test.
This is a small near-field synthesized-speech test, not a false-wake or across-room
benchmark. Remaining gap: occasional missing first word and cold TTS loading.

Tracked `patches/echo-dot-assist-playback-drain.patch` fixes the observed
asynchronous MixerDrain behavior. The host C regression checks that close waits
for queued bytes, while cancellation flushes immediately. Controller regression
checks reject a brief noise pulse as speech, retain three turns, and allow
unbounded idle waiting. No new package dependency was introduced for E12.

Automatic review rejected the proposed permanent boot service and SELinux
policy install before the command executed, citing lack of explicit approval
for that persistent privileged change. User approval requested. The staging
files exist, but there is no installed /system/hassmic service from this trial.
Current setup survives this session but is not yet configured for Echo reboot.


Final regression run: Mac 163 passed; Pi 161 passed, 2 skipped (optional host
C/source-cache checks). Mac self_test.py could not run because its environment
has no Vosk; the Pi self-test is the applicable runtime check. git diff --check
passed. Artifact hashes are saved in
`logs/echo-dot-assist-E12-build/final-artifact-sha256.txt`.


## Pi management repair

The reported 15:48 EchoMuse timeout was historical output in jarvis_voice.log;
the temporary Wyoming controller had been logging separately. The normal Pi
launcher now selects hassmic_jarvis.py when JARVIS_HASSMIC_HOST is configured,
and uses the normal log. The host was configured on the Pi. Both the repository
and separately installed /usr/local/bin/jarvis command now find the controller
child as well as the lock process. Verified a complete restart and a fresh
hassmic_connected event at 16:24:23.790. Existing historical logs were retained.
This did not install or change the rejected Echo boot service/SELinux policy.


Follow-up restart repair: found PID 7204 orphaned and retaining the lock after
the user's stop. Switched both Pi launchers to no-fork locking (`flock -F`),
scoped legacy lock-process matching to the project, and added real-process
management regression coverage for two restarts, preserved archived logs, and
startup failure reporting. Current-run logs are separated from archived logs;
`tail -F` follows the new file. Repeated actual restart via an interactive Bash
shell, checking one runtime/lock owner and a fresh connection event.

## Announcement repair (2026-10-21)

Found the controller stopped after `EOFError: Echo disconnected`. The Wyoming
migration had also omitted startup of the existing authenticated receive API,
so service announcements could not reach this runtime even when connected.
Added the command server and a bounded idle-time announcement queue, direct
Wyoming playback with follow-up, and five-second reconnect after session errors.
The receive server stays running across reconnects. Failed in-flight messages
are logged without replay; pending messages remain queued until reconnect.

Deployed to Pi and restarted. LAN `/health` returned success. Authenticated
status reported `echo_connected=true`; the test announcement queued at
00:37:05.948, started at 00:37:06.192, and received Echo playback acknowledgment
at 00:37:11.760. Follow-up opened immediately for 20 seconds and returned to
standby at 00:37:31.845 without speech. These are device acknowledgment timings,
not an independent microphone recording of speaker output.

Reconnect and processing-failure recovery pass injected regression tests. A
controlled live socket-reset attempt using `ss -K` was unsupported by the Pi
kernel (`RTNETLINK: Invalid argument`), so hardware disconnect recovery was not
verified in this run. The Echo connection stayed established.


## Loaded-model reporting (2026-10-21)

`patches/echo-dot-assist-model-status.patch` extends the patched Wyoming info
handshake with `loaded_wake_models`. The microWakeWord loader publishes a locked
snapshot only after initialization succeeds; closing or failing a load clears
it. Names are JSON-escaped and SHA256 comes from the loaded TFLite bytes. No
additional HTTP login, ADB connection, or model-file read is needed by the Pi.

The logging-only binary was built with the existing Darwin NDK and installed
into the temporary Echo runtime. Backup on Echo:
`/data/local/hassmic/hassmic.before-model-status-20261021`.
No boot service or model selection changed. After Pi restart at 15:10:45,
`jarvis logs` confirmed Hey Jarvis (0.97) and computer (0.66), with hashes matching
the original downloaded models. Trained candidates are still inactive.

Host tests cover successful load, retained fingerprint after disk removal,
close/failure clearing, JSON escaping, and missing/invalid protocol reports.

## Permanent startup — 2026-10-21

User explicitly approved the privileged boot service, required init-to-su
SELinux transition, and disabling Alexa/Amazon update services. Installed
the pinned upstream boot/main/sysinstall/lockdown scripts with the currently
working patched binary, using PROTO=wyoming and ARGS="-p 16700 -n Jarvis-Echo
-a 0 -z 0 -i 0 -E". Both personalized wake selections remain unchanged.
System policy before install is retained on-device at /sepolicy.pre-hassmic.
Private local backup of policy and Jarvis data: logs/echo-persistent-20261021/backup.
This is not a full firmware backup.

Boot verification confirmed init services hassmic and hassmic_fw running,
Alexa puffin stopped, and saved the saved Wi-Fi network Wi-Fi joining automatically.
An idle Pi connection originally remained stale after Echo reboot. TCP keepalive
now detects the lost satellite and invokes the existing reconnect loop without
requiring a Pi restart. Linux probes: idle 15 s, interval 5 s, count 3; other
platforms use supported options. No speech or API query is sent by these probes.

Removing /data/local/hassmic/hassmic.conf and rebooting disables the startup
service's actions (stock behavior). Full removal uses the upstream sysinstall.sh
uninstall path, which restores the saved policy and LED configuration.

Final verification: Pi PID 20862 remained running across the Echo reboot;
it detected the dead socket at 22:15:12 and reconnected at 22:15:45, logging
both exact personalized model hashes and wake_listen_started. Evidence:
logs/echo-persistent-20261021/{pi-reconnect.log,echo-boot.log}. This verifies
software reboot recovery; moving to a wall adapter is the user's next physical
check. Mac tests 216 passed / 2 skipped; Pi 215 passed / 3 skipped and self-test
passed. Mac self-test cannot run because local Vosk is absent. Lock and diff
checks passed.
