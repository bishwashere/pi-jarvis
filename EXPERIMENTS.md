# Jarvis voice experiments

Historical experiment record beginning 2026-10-20. See README.md for the current architecture. This file distinguishes deployed settings, user feedback,
and proposed trials. A successful startup is not proof of recognition accuracy.

## Historical pipeline (2026-10-20)

| Phase | Current implementation | How it works |
| --- | --- | --- |
| Microphone | Echo Dot 2 through EchoMuse | Streams mono 16 kHz audio to the Pi. |
| Wake detection | Vosk `vosk-model-en-us-0.22-lgraph` plus Echo openWakeWord `hey_jarvis_v0.1` | Vosk matches transcribed phrases; Echo reports acoustic detections. Two P10S acoustic tests confirmed openWakeWord triggers on 2026-10-20; this does not establish accuracy on the user's voice. |
| Command capture | Audio level threshold and silence | Records up to 60 seconds, ending after speech followed by 1.5 seconds below RMS 1000 (E05/E10 overrides). |
| Transcription | Local `whisper.cpp`, `tiny.en` | Transcribes the saved recording after capture ends. |
| Response | Configured Jarvis/Passer API | Receives the completed command text and returns a response. |
| Voice generation | Local Piper, `en_US-lessac-medium`, cached Python backend | User approved Lessac. Reuses the loaded model; generates a WAV before playback. |
| Speaker | Echo Dot 2 through EchoMuse | Plays the synthesized response. |

The microphone already streams audio. A streaming transcription trial changes
when recognition happens: while chunks arrive instead of after saving the
whole utterance. It still consumes audio.

## Experiment register

| ID | Change | Status | Observation / decision |
| --- | --- | --- | --- |
| E00 | Original small Vosk model, local Whisper tiny.en, Piper Amy | Previous baseline | User reports Vosk transcripts do not match speech, dislikes capture-then-transcribe delay and describes the reply voice as robotic. |
| E01 | Replace small Vosk with `vosk-model-en-us-0.22-lgraph` | Deployed; user tested | Model loads and Echo reconnects. User reports Jarvis still never recognized; “hey computer” triggers. Logs show the actual matched phrase was standalone “computer” within “a computer.” No demonstrated improvement for Jarvis. |
| E01a | Add standalone “hey” and “hello” to the Vosk wake phrases | Deployed 2026-10-20, Pi log time 09:38; awaiting user test | E01 model retained. 123 tests and the model smoke test passed; Echo reconnected. A wake on “hey” alone is not evidence that “Jarvis” was recognized. |
| E02 | Streaming Vosk command transcription | Tested; REJECTED; Whisper restored | Question became `the to plus` in 3.599 s after playback ended. Follow-up produced `the` without more test speech. Accuracy regressed; test stopped and service restored. |
| E03 | Piper Lessac instead of Amy, with Whisper restored | Kept; user approved Lessac | Correct arithmetic transcript and answer. Answer synthesis 2.662 s; API worker reply to first answer packet 6.923 s. No measured latency advantage. Matching longer voice samples saved. |
| E04 | Keep Lessac loaded through Piper's Python API | Tested; kept | Answer synthesis fell from 2.662 s to 0.089 s; same transcript and answer. |
| E05 | Raise recording speech threshold from 420 to 1000 | Kept after normal and quieter tests | Recording 4.5 s versus 11.3 s; correct transcript. Silent follow-up no longer generated noise transcripts or clarification. |
| E06 | Preserve numeric plus in command cleanup | Tested; kept | Correct `what is 2 plus 2` reached API in live test. |
| E07 | Disable waiting announcements | Tested; kept; recovery repeat passed | Correct answer; actual API worker reply to first answer PCM 0.157 s. |
| E08 | Compare Whisper thread counts 1, 2, 4 | Interrupted; NOT deployed | One thread 2.761 s, two 1.506 s, same transcript; Pi rebooted during four-thread test. Cause unconfirmed. |

E01 is selected with:

```dotenv
JARVIS_VOSK_MODEL_PATH=runtime/cache/vosk-model-en-us-0.22-lgraph
```

E02 can be selected with `JARVIS_COMMAND_STT_ENGINE=vosk`; return to the current
command engine with `JARVIS_COMMAND_STT_ENGINE=whisper`, followed by
`jarvis restart`. Vosk's existing endpoint waits for a final recognition result
and then checks for 0.7 seconds without a transcript update; Whisper uses
2 seconds below its audio-level threshold. Record cutoffs as well as latency.

No restricted wake grammar was deployed. Its local trial changes were removed
after the user clarified that recognition accuracy was the target.

## Current-set acoustic baseline: 2026-10-20

P10S USB speaker at PCM 85% -> Echo Dot microphone -> existing Jarvis runtime.
Piper Amy generated the stimulus, “Hey Jarvis,” then “What is two plus two?”
The runner waited for command recording to start before playing the question.
No recognition, capture, or voice setting changed between the two runs.
Millisecond voice timestamps and speech-output timing events were added before
the second run; 125 unit tests and the Pi smoke test passed.

| Run | Wake detector / score | Whisper transcript | Spoken answer |
| --- | --- | --- | --- |
| `acoustic-20261020-094326` | openWakeWord / 0.57926035 | `What is 2+2?` | `4` |
| `acoustic-20261020-094635` | openWakeWord / 0.97698 | `What is 2 + 2?` | `4` |

Both runs used the existing 0.5 openWakeWord threshold. These are two synthetic
speech trials, not a measured success rate on varied voices or background noise.
The first run may include overlapping room speech and has only second-resolution
runtime timestamps; use the second run for the detailed baseline below.

### Detailed second-run timing

Times below use the Pi's clock. The playback timestamps bracket `aplay`, not a
separate measurement of when sound physically reached the Echo microphone.

| Event / interval | Measurement |
| --- | --- |
| P10S wake playback | 09:46:41.467–09:46:42.532; WAV duration 0.906 s |
| Echo wake event received | 09:46:42.618; 1.151 s after playback call began; reported event age 41 ms |
| Jarvis accepts wake | 09:46:43.294; 0.676 s after receiving Echo event |
| Greeting synthesis | 2.451 s |
| Greeting first PCM sent | 09:46:45.821 |
| Command recording starts | 09:46:49.147; 5.853 s after wake acceptance |
| P10S question playback | 09:46:49.742–09:46:51.558; WAV duration 1.707 s |
| Recording ends | 09:47:00.686; 11.5 s total, 9.128 s after question playback returned |
| Whisper transcript ready | 09:47:03.365; 2.679 s after recording ended |
| Capture-confirmation tone / handoff | API request starts 09:47:04.751, 1.386 s after transcript |
| Actual API worker response log | 09:47:10, with only second precision |
| “Let me check” output finishes | 09:47:13.927 |
| Conversation loop handles API result | 09:47:13.942; later than the API worker response |
| Answer synthesis | 2.543 s |
| Answer first PCM sent | 09:47:16.513; approximately 5.5–6.5 s after API worker response |
| Answer playback call returns | 09:47:18.440; answer WAV 0.720 s; call includes estimated buffer/drain wait |
| Follow-up cycle | 09:47:18.440–09:47:39.837; 21.397 s, including transcription and clarification speech |
| Returns to wake listening | 09:47:44.637, after standby speech; 26.197 s after answer playback returned |
| Accepted wake to standby | 61.343 s |

The `pasture_response_received` voice event occurs when the main loop handles
the result; it is NOT the time the API worker first received the response.
The latter is the `Pasture response` line. Their difference matters when
the main loop is busy speaking “Let me check.”

### Findings to compare in the next trial

- openWakeWord genuinely detected the synthetic “Hey Jarvis” in both runs.
- The second recording marked speech at 09:46:49.165, before question playback
  began at 09:46:49.742: input RMS 560 exceeded the 420 threshold. Other audio
  was being treated as speech. Its exact source was not established.
- During follow-up, with no second test question played, the input again crossed
  the speech threshold. Whisper returned `(upbeat music)` twice; both transcripts
were ignored, but the first triggered an unnecessary clarification.
- API wait itself is excluded from the response-output metric. A response was
  already available while the “Let me check” utterance was still being generated
  or played. Answer synthesis then added 2.543 s.
- Whisper recognized the arithmetic question, but text cleanup changed
  `What is 2 + 2?` to `what is 2 2`, losing the operator before the API call.
  The API still answered `4`. This normalization issue remains unfixed.
- No independent microphone measured the physical onset of the Echo's reply.
  First PCM sent and playback-call return are transport/software timings.
- Voice naturalness still needs the user's rating; successful playback does not
  establish that the voice sounds good.

Evidence on Pi: `logs/acoustic-20261020-094326/` and
`logs/acoustic-20261020-094635/` contain stimulus WAVs, `observed.log` and
`result.json`. Local copies are under `logs/acoustic-results-20261020/`.
The bounded probe is saved on the Pi as `runtime/cache/acoustic_probe.py`.
Run from the checkout with
`PYTHONPATH=. runtime/venv/bin/python runtime/cache/acoustic_probe.py`.
It plays through P10S and contacts the real assistant through the normal
acoustic path; run only as an intentional hardware test.

## E02 and E03 results

E02 ran at Pi time 10:01:43 on 2026-10-20. The expected question was
“What is two plus two?”; streaming Vosk returned `the to plus`. The API
asked for clarification. A later `the` transcript triggered another API request
despite no additional automated input. The probe was interrupted deliberately
after saving its results, and Whisper was restored. Do not count the runner's
`answer_text_logged=true` as a successful answer: it only means an answer event
occurred, and its content was a clarification.

E03 ran at 10:04:45 with
`JARVIS_PIPER_MODEL_PATH=runtime/cache/piper/en_US-lessac-medium.onnx`.
The [official Lessac medium voice](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/medium)
was downloaded and smoke-tested. The exact baseline stimulus WAVs were reused
from this run onward; the stimulus voice remains Amy while the response voice
changes.

| Metric | E02 streaming Vosk + Amy | E03 Whisper + Lessac |
| --- | --- | --- |
| Expected question | What is two plus two? | What is two plus two? |
| Transcript | `the to plus` | `What is 2+2?` |
| End of test playback to transcript | 3.599 s | 10.734 s |
| Answer | Clarification requested | `4` |
| Actual API worker reply to answer PCM | 3.050 s | 6.923 s |
| Answer synthesis | 2.728 s | 2.662 s |
| Follow-up behavior | Unprompted `the`; clarification loop | Non-command noise transcripts; returned to standby |
| Decision | Reject due to accuracy | User approved Lessac; keep voice |

In E03 an openWakeWord detection arrived at 10:04:46.505 (score 0.8608962),
but Vosk was the accepted detector at 10:04:46.998, matching standalone `hey`.
The existing code can finish a Vosk decode and accept its match before consuming
an Echo event that arrived during decoding. The accepted detector is therefore
not necessarily the first detector to report.

The paired voice samples use the sentence “The weather looks pleasant today.
We can take our time and work through this together.” Amy generation took
4.219 s for 5.097 s of audio; Lessac took 4.027 s for 4.191 s of audio.
These single samples do not establish a quality winner or reliable performance
difference. The user subsequently approved Lessac; voice selection is fixed for further trials.

Evidence: `logs/acoustic-20261020-100138/` (E02),
`logs/acoustic-20261020-100445/` (E03), and
`logs/voice-comparison-20261020/` (paired voice samples), on the Pi.
Copies are under local `logs/acoustic-results-20261020/logs/`.

## Fixes retained across experiments

- Vosk quick-command guesses no longer stop Whisper recording or bypass its
  transcript. Partial quick-command guesses are ignored.
- Logs distinguish Vosk transcripts and accepted Vosk/openWakeWord wakes.
- The example `[openWakeWord] Speech processed | peak score=...` line is NOT
  implemented. No periodic detector-statistics logging was added.
- Original bundled model assets remain available for rollback.

## Fast comparison procedure

1. Activate one experiment and record the start time and exact settings.
2. Use the same position, speaking volume, and sentences for each trial.
3. Say “Hey Jarvis” three times, separately. Count successful wakes and note
   which detector wins. Also speak ordinary sentences to check accidental wakes.
4. For command-transcription comparisons, use “Hey computer” if necessary to
   get past the known Jarvis problem, wait for the greeting, and repeat:
   “What time is it?”, “Tell me a short joke”, and
   “Nothing happens when I ask for the weather.” Include one natural pause.
5. For voice comparisons, play the same sentence:
   “Hello. I'm ready when you are. What would you like to do?”
6. Record what was said, the final transcript, approximate response delay,
   any cutoff, and voice preference. Mark unavailable measurements as unknown.
7. Keep, revert, or proceed to the next numbered experiment based on the result.

Use short two-to-three-minute trials. An E02 result should be followed by E03
with transcription held fixed, rather than changing recognition and voice
together.

## Result entry template

```text
Experiment:
Started:
Settings changed:
What I said:
What it transcribed:
Wake successes / attempts:
Approximate delay after finishing speech:
Cut off early?:
Voice naturalness / preference:
Decision: keep / revert / next trial
```

## E04–E05: cached voice and recording threshold

E04 (`logs/acoustic-20261020-100912/`) retained Whisper and Lessac and
changed only Piper execution to its cached Python backend. Cold greeting
synthesis took 2.304 s; the warm answer took 0.089 s. Recording still took
11.3 s, ending 8.897 s after test playback ended. Kept the cached backend.

E05 (`logs/acoustic-20261020-101400/`) changed only
`JARVIS_COMMAND_AUDIO_RMS_THRESHOLD=1000`, retaining the two-second silence
window. Speech began 0.9 s into capture, with RMS 8002; capture took 4.5 s
and ended 2.091 s after test playback ended. Whisper returned `What is 2+2?`
2.653 s later (4.744 s after playback ended). The answer was `4`; warm
synthesis took 0.079 s. Silent follow-up lasted 20.3 s, detected no speech
(peak RMS 917), and caused no transcription or clarification.

These are acoustic fixture tests, not proof of recognition on the user's
voice. The quieter repeat at P10S PCM 65% (`logs/acoustic-20261020-101458/`)
also returned the full correct transcript, with recording 4.4 s and no false
follow-up speech. P10S volume was restored to 85%. E05 is retained provisionally;
quiet human voices and pauses still need broader coverage.

E06 (`logs/acoustic-20261020-101729/`) fixes the confirmed loss of numeric `+`
during command cleanup. The real transcript `What is 2+2?` now becomes
`what is 2 plus 2` in the API request. Answer was `4`, recording 4.4 s,
Whisper 2.6 s. Local and Pi suites: 136 passed. Numeric plus is expanded;
this does not claim to fix every punctuation or number-formatting issue.

E07 disables waiting announcements using `JARVIS_WAITING_ANNOUNCEMENTS=false`.
E05's actual API worker response arrived at 10:14:18.205 during Checking
playback, and the answer's first PCM packet was not sent until 10:14:19.996
(1.791 s later). This trial targets that blocking announcement delay.
The setting defaults to true; local and Pi suites: 138 passed.

### E07 result and interrupted E08 benchmark

E07 (`logs/acoustic-20261020-101912/`) returned `4` after accepting
`what is 2 plus 2`. Recording was 4.5 s and Whisper 2.6 s. Actual API worker
reply was 10:19:30.869; first answer PCM 10:19:31.026 (0.157 s). The
main-loop response event was 10:19:30.948, so using that timestamp alone
would understate worker-to-output latency. This request completed before
the old four-second announcement threshold; it does not alone prove the
size of the improvement for overlapping announcements. The unit tests
confirm that disabled announcements do not run and answers still play.

E08 ran offline transcription against the same captured command, keeping the
service configured for one thread. Tool output reported identical `What is
2+2?` transcripts at 2.761 s (one thread) and 1.506 s (two threads). The
four-thread attempt did not return: SSH dropped and uptime confirmed a
reboot around 10:21. There was no persistent prior-boot journal; current
firmware reported throttled=0x0 and temperature 62.6 C. Neither proves the
pre-reboot cause. The benchmark directory did not survive. No thread-count
change was deployed. User was asked whether they restarted the Pi.

After reboot, code hashes and retained settings matched the tested versions.
The completed E06/E07 evidence was recovered locally; E07 log tails may be
incomplete because recently buffered writes were lost. The recovery probe (`logs/acoustic-20261020-102153/`) used “What is six
plus seven?” with the existing one-thread configuration. It captured 4.5 s,
transcribed `What is 6+7?`, sent `what is 6 plus 7`, and answered `13`.
Whisper took 6.1 s after reboot, slower than previous 2.6–2.7 s; cause is
unconfirmed. Cold greeting synthesis was also slower (5.006 s), while warm
answer synthesis was 0.096 s. Silent follow-up stayed open 20.3 s with no
false speech, then returned to wake mode. High-thread experiments remain
paused pending understanding of the reboot; one-thread service is running.

## E09–E11: pauses and continuous conversation (2026-10-20 afternoon)

Lessac and one-thread Whisper remain fixed. Pi uptime was five hours. Firmware
reported `throttled=0x50000`: historical undervoltage and throttling flags,
not active throttling at that reading ([official bit definitions](https://www.raspberrypi.com/documentation/computers/os.html#get_throttled)).
This is not proof of the earlier reboot cause. Recent API calls had HTTP 500
errors, but both following arithmetic probes received valid replies.

| Trial | Change | Observed result | Decision |
| --- | --- | --- | --- |
| E09 | Current 2.0 s silence window; fixed phrase with 1.0 s inserted pause | Full `What is 6+7?`; capture 5.5 s, Whisper 2.7 s, answer 13 | Baseline |
| E10 | Same fixture, silence window 1.5 s | Full `What is? Six plus seven?`; cleaned correctly; capture 5.0 s, Whisper 2.7 s, answer 13 | Retain provisionally for conversation trial |
| E11 | Remove standalone hey, keep hey Jarvis; three contextual questions after one wake | Correct answers 4, 7, 14; only initial question needed a wake | Kept |

E09 evidence: `logs/acoustic-20261020-152146/`. E10 evidence:
`logs/acoustic-20261020-152329/`. Shared fixture:
`logs/pause-fixture-20261020/question.wav`. Both tests ended with about 20 s
of silent follow-up and no false command. The inserted gap is in addition to
any silence already in the synthesized clips; this is not a human pause test.

Config now supports `JARVIS_COMMAND_SILENCE_SECONDS` (default remains 2.0;
Pi trial override 1.5). 146 tests passed locally and the Pi for this change.
Standalone `hey` is removed at the user's request; `hey jarvis`, `hey computer`,
and the other configured wake phrases remain. This changes Vosk phrase matching;
Echo's hey-Jarvis acoustic model remains active.

E11 uses one Hey Jarvis, then “What is two plus two?”, “Add three to that”,
and “Now multiply that by two”. Expected replies are 4, 7, 14. Follow-up
questions are played only when capture has resumed after each answer; no
additional wake is played. This separates continuous listening from agent
context retention.

### E11 three-turn result

One acoustic Hey Jarvis started the conversation. The following were all
transcribed and accepted in the same conversation:

| Turn | Spoken | Accepted transcript | Answer | Capture / Whisper |
| --- | --- | --- | --- | --- |
| 1 | What is two plus two? | what is 2 plus 2 | 4 | 4.1 / 2.6 s |
| 2 | Add three to that. | add three to that | 7 | 3.9 / 2.6 s |
| 3 | Now multiply that by two. | now multiply that by 2 | 14 | 4.5 / 2.7 s |

Turns 2 and 3 were logged as `kind=followup`; no extra wake was spoken.
The API returned `continue_listening=False` after each answer, but Jarvis's
existing 20-second follow-up window correctly allowed another question.
The test confirms three-turn listening and arithmetic context retention,
not indefinite conversation or barge-in while the speaker is playing.
Lessac stayed fixed. Warm answer synthesis was 0.060, 0.073, 0.093 s.

148 tests passed locally and on the Pi. Pi self-test passed without hardware
or API access. `git diff --check` passed. `uv` is unavailable locally, so
lock validation could not run; no dependency changes were made in these trials.

E11 evidence: `logs/multiturn-20261020-152516/`. Exactly one accepted wake;
three correct answers; returned to standby after 20.4 s of silent follow-up.
Standalone “Hey.” was then played three times, each observed for five seconds
following playback: zero accepted wakes. Evidence: `logs/hey-negative-20261020/`.
This is a small negative test, not a general false-wake-rate estimate.
Probe scripts and evidence were copied locally under
`logs/acoustic-results-20261020/`.

## E12: echo-dot-assist → direct Jarvis hardware trial

Migrated the backed-up Echo Dot 2 on the Mac to supported Fire OS 6574.1,
installed the temporary patched satellite, and connected over Wi-Fi directly to
Pi Whisper → Jarvis API → Piper Lessac. No Home Assistant.

E12a: stock Alexa detected the wake and three questions produced 4/7/14, but
“Add three” was misheard. Found asynchronous mixer drain and chime-triggered
follow-up audio. E12b: fixed drain and disabled chime; all three transcriptions
correct, 4/7/14 again, but residual sound caused early empty follow-up.
E12c: Hey Jarvis microWakeWord + 120ms speech-start requirement; wake accepted,
three answers 4/7/14, full 20s final follow-up, then quiet standby. “Add three”
lost “Add”, so recognition still needs tuning.

Whisper: 2.61–2.74s. API response to audio send: ~2.1s cold Piper, ~0.1s warm.
Physical room recording includes audible replies (separate transcript found
Seven and 14); acoustic first-sample latency is not yet measured.
Evidence is saved locally under `logs/e12-hardware-results/`.

Persistent Echo startup installation was blocked by automatic approval review;
explicit user approval is pending. Temporary Echo and Pi processes remain active.
See [E12-ECHO-DOT-ASSIST.md](E12-ECHO-DOT-ASSIST.md) for versions, fixes, results,
and remaining limitations.

### E12 announcement repair — 2026-10-21

Restored the authenticated receive API in the direct Echo controller, queued
announcements for idle playback, and added reconnect after session failures.
On Pi, the test announcement received a `played` acknowledgment after 5.568 s
from processing start and opened the 20-second follow-up, then returned to
standby. LAN health and authenticated connected status passed. Reconnect was
regression-tested with injected disconnect and synthesis errors; live socket
reset was unavailable on this Pi kernel. Details in E12-ECHO-DOT-ASSIST.md.

## E13: repeated P10S → Echo wake tests (2026-10-21)

Kept the E12 Hey Jarvis microWakeWord v2 model (0.97 cutoff), Whisper, Jarvis,
and Lessac. Added explicit `wake_listen_started` and `wake_heard` events to the
Pi controller; automatic follow-up is not logged as a fresh wake. The Echo's
Wyoming metadata hardcodes the name Alexa even with microWakeWord, so actual
keyword/score evidence is retained from its own detector log instead.

Baseline: P10S PCM 85%, same existing Hey Jarvis WAV, six repetitions separated
by full 25-second no-command windows. All six detected, with status reporting
the Echo connected before and after each attempt. Detection reached the Pi
0.997–1.126 seconds after playback command start. Echo detection means were
252, 253, 254, 249, 254, 254 out of 255. No model tuning was needed for these
synthetic baseline trials; this does not establish live human wake accuracy.

A seventh wake was followed shortly by the three-question fixture. Answers were
4, 7, 14 with no extra wake required. Whisper transcribed the middle question as
“3 to that” instead of “Add three to that.” Final follow-up returned to standby
after about 20 seconds. Cold response-to-send was 2.181 seconds; later responses
were 0.108 and 0.110 seconds. These are software timings and Echo acknowledgments,
not independently measured speaker audio. Evidence: `logs/e13-wake-repeat/`.

Quieter follow-up set: scaled only the wake waveform to 0.5, 0.25, and 0.125
amplitude (approximately −6, −12, and −18 dB); left the device volume unchanged.
All three detected and each then captured “What is two plus two?” and answered
4. Their on-Echo detection scores were 247, 254, and 254/255. Total across this
run: 10/10 synthetic wakes (six repeats, one conversation wake, three quieter
wakes), six answered questions. The intermittent human wake miss was not
reproduced, so no wake sensitivity change was made. Updated logging verified by
173 local tests and 172 Pi tests, plus the Pi self-test (platform-specific skips
excluded). The open terminal tail was checked against the current logfile inode;
it was reading the current file. Quiet intervals corresponded to no-command
and follow-up listening windows, rather than a stopped log writer.

## E14: arithmetic → unrelated topic → topical follow-up (2026-10-21)

Asked, after one Hey Jarvis wake: “What is two plus two?”, “Add three to that”,
“Now multiply that by two”, “Why is the sky blue? Give a short answer”, then
“Why does it look red at sunset? Keep it brief.” No return to arithmetic.

First attempt woke and answered 4, but the next fixture was not detected as
speech; the 20-second follow-up expired. The controller remained connected.
The synthesized fixture was not quieter overall than the older fixture (WAV
RMS 4821 vs 4427); that does not identify the cause of the capture miss.
Retained this failed attempt in the evidence. Retry reused the previous known
number recordings and 0.7-second post-listen pause instead of 1 second; because
both changed, the passing retry does not establish which affected the miss.

Retry completed all five turns with one wake: 4, 7, 14, a blue-light-scattering
explanation, then a sunset explanation. The final transcription changed “at
sunset” to “It's sunset” but the response stayed on topic. All five replies
received Echo playback acknowledgments. No runtime/model configuration changes.
Evidence: `logs/e14-topic-switch/` and corresponding timestamped Pi directories.

## E15: Computer alongside Hey Jarvis (2026-10-21)

User requested only Jarvis and Computer, explicitly excluding Alexa. Downloaded
but never installed/enabled Alexa. Added community Computer model from
JohnnyPrimus/Custom_V2_MicroWakeWords, models/computer (author Leland Olney,
v2 cutoff 0.66, window 5), leaving official ESPHome Hey Jarvis v2 at 0.97.
Source URL and SHA256 evidence are in logs/e15-wake-alternative. Enabled the two
IDs in Echo state/mww_word and restarted only the temporary satellite process.
Both models loaded; no firmware, boot service, or SELinux changes.

Actual disconnect recovery was observed: Pi logged Echo disconnected at
13:52:22.051 and reconnected at 13:52:27.058 without restarting the Pi controller.
This supplies hardware evidence missing from the earlier ss -K attempt.

User reported that the Echo is farther away now than during previous tests.
Exact distance and time of repositioning were not measured. Treat this run as
farther-placement testing, not a controlled comparison with E13/E14. Do not
attribute accuracy changes solely to the newly added model.

Computer triggered on the initial attempt and two repeats, confirmed by the
Echo's own second-slot detector log (means 168, 178, 176/255). The first two
attempts missed the subsequent question and returned to standby; the third
transcribed “What is 2 plus 2?” and answered 4. Recorded detection separately
from complete command success. No programmatic detection event or warm-up
command was sent: P10S playback supplied the acoustic wake and question.

During the third Computer trial the user continued the conversation. The first
live “add four” was transcribed as “Add forward to it”; the user clarified that
this was their speech. Their repeat was transcribed as “Add four” and Jarvis
answered 8. The live conversation exceeded the harness's bounded wait for
standby, so it stopped before the planned Hey Jarvis control. This was a test
harness exit, not a controller failure. No further synthetic playback was sent
while the user was speaking. Hey Jarvis remains loaded but was not acoustically
retested in this final set. Initial synthetic result: Computer 3/3 wake triggers,
1/3 immediate scripted questions answered; two command-capture misses remain.

## E16: local primary-user setup collection

Added local “do setup” routing to the direct Echo controller. The guided flow
captures quiet room audio and Computer/Hey Jarvis plus everyday phrases at
close, far, and side positions. Each phrase is requested twice; samples are
saved with expected phrase, transcript, position label, and fixed-block RMS
statistics. Capture bypasses production VAD so quiet training candidates are
not discarded. Cancel/interruption preserves partial files without replacing
prior completed-session pointers. Prompts and samples stay local; no setup
phrases are sent to the agent API.

This is dataset collection, not implemented neural training or applied VAD
calibration. Manifests explicitly mark model_status=not_trained and
settings_applied=false. Samples require review/segmentation and separate test
recordings; the processed command stream differs from the pre-wake stream, so
training suitability needs validation. No real user enrollment was started by
the agent. The user starts with “Computer, do setup.”

Validation: local 187 passed/1 skipped; Pi 186 passed/2 skipped; Pi self-test
passed. Included quiet capture, exact audio duration, format rejection, both
phrases at all positions, cancel/disconnect preservation, config override in
a fresh process, and setup interception before the remote API. These are mocked
regression checks, not a completed physical enrollment or trained-model test.

E16 setup trigger repair: user logs showed Whisper returning “do set up do set
up” and “do set up”. The initial exact-match handler accepted only “do setup”,
so these were sent to the agent API. Canonicalize set up/setup and accept up to
three repetitions of explicit setup intents. Cancellation gets the same spelling
and repetition handling. Anchored matching still rejects commands such as “do
set up the lights” and questions about setup. Regression checks include the
actual logged transcripts and confirm that they never reach the remote agent.
Local suite: 199 passed, 1 skipped; Pi: 198 passed, 2 skipped; Pi self-test passed.

E16 acoustic trigger verification: the P10S said “Computer”, then “Do set up.
Do set up.” Whisper returned the exact previously failing spelling/repetition.
Setup intercepted it locally at 14:07:16.570, played its introduction, recorded
close_noise and then close_computer. The speaker said “Cancel setup”; Whisper
recognized it and the controller logged voice_setup_cancelled at 14:07:54.807.
No enrollment completed or model/settings changed. The cancelled session is
20261021-140716-c31b3b21; it contains test audio, not a primary-user training set.

Stale terminal root cause: ~/.local/bin/jarvis was an older personal launcher
using tail -n 80 -f, while /usr/local/bin/jarvis already used -F. Updated both
copies and retained optional line-count support. Old running viewers need to
be reopened once. Added a Linux regression exercising actual file replacement
under the log viewer, without restarting or touching the live service.

## Command management audit (2026-10-21)

Verified repository, ~/.local/bin, and /usr/local/bin launchers matched. Initial
live check encountered overlapping lifecycle commands: restart observed a
stopped process while another launch appeared from the user's terminal. Added
a per-checkout flock around start/stop/restart (15-second bounded wait), closing
the lock descriptor in the launched runtime. Status and logs remain independent.
An isolated regression concurrently restarts twice and verifies both succeed.
All six launcher regressions passed on Pi, including real log rotation.

Repeated live checks after deployment passed: running/stopped status (exit 0/1),
start when already running without duplication, stop when already stopped,
start, restart with a new single controller PID, logs 0 following the replacement
file through restart to a fresh hassmic_connected event, and invalid-command
usage (exit 2) through both installed launchers. Announcement health returned
ok. Final running controller PID 15448. Evidence is in Pi
logs/command-verification/result.json and log-viewer.txt. Shell syntax and
whitespace checks passed. Jarvis was left running and connected.

### E17 — primary-user wake-word training (2026-10-21)

With explicit permission, copied the completed 17-clip enrollment session to
this Mac's private ignored training folder; no external upload. Trained new
MixedNet candidates for Hey Jarvis and Computer using close/far recordings,
keeping side-position recordings out of fitting. Iterated on false wakes with
local Piper negatives and continuous frontend feature windows. Selected Hey
Jarvis candidate-v4 and Computer candidate-v2 each detect all six recorded
repetitions (including two excluded from training), versus 0/6 and 1/6 for the
original models in this replay. Zero false activations among 54 available
non-target clips per selected model, but these include fitting data; the small,
reused validation set does not establish an everyday false-wake rate.

Models are **trained, not deployed**. Fresh live speech and pre-wake-path testing
remain necessary. Private results, scripts, checksums and limitations:
`logs/voice-training/primary/trained-20261021/REPORT.md`. Original Echo models
remain active. Setup prompts now say stay where you are between samples;
longer everyday phrases record for 14 seconds instead of 8. Those UX changes
were synced to Pi and restarted with Echo reconnection confirmed. Mac/Pi tests:
199 passed, 2 skipped; Pi self-test, lock check and diff check passed. Mac
self-test unavailable because its environment lacks Vosk.


E17 activation — 2026-10-21 17:04:40 Echo time: user explicitly requested
activation. Installed the selected models under `primary_hey_jarvis` and
`primary_computer`, preserved the original model directories and previous
selection, and restarted the temporary Echo runtime and Jarvis. Both
`wake_model_loaded` SHA256 values exactly match the trained bundle; cutoff 0.90,
five-frame window. `wake_listen_started` confirmed. Models are now active;
fresh live speech performance is not yet verified. Evidence and rollback path:
`logs/voice-training/primary/activation-20261021/result.json` and `startup.log`.

### E18 — acoustic multi-turn/AI audit (2026-10-21)

Ran P10S → Echo tests with personalized wake models and Lessac Medium at 1.08.
Three four-turn conversations completed after retrying a missed initial wake:
arithmetic/context, home/light/sensor status, and hypothetical Boston/weather/news.
No device mutations requested. Arithmetic 4→7→14 and location context passed;
news headline independently matched today's AP report. Home status and weather
queries were unavailable to the agent. Whisper substituted/lost some words.
Synthetic Computer wakes missed 3/3; recorded voice replay included clear wakes,
one miss and one ambiguous late event. Not a live-user accuracy estimate.
Follow-up silence timeout 19.94–20.12 s; initial silence timeout 24.99 s.
End-of-prompt to reply playback call 7.25–17.63 s, mostly backend latency
(3.23–13.37 s). Existing playback-sent log precedes play(), so first audible
sound latency is not measured. Full issue table and raw results:
`logs/conversation-audit/REPORT.md`. Production settings were not changed.

### E19 — repeat acoustic audit (2026-10-21)

Reused E18 audio fixtures through P10S → Echo. Recorded Computer detected 3/3;
synthetic Computer missed 2/2. Six prompts reached Whisper (2.58–2.96 s),
but all backend replies reported the AI limit, so further semantic testing
was stopped. Quota replies played successfully; controller still opened
follow-up windows despite continue_listening=false. “Add” was again dropped
from “Add three to that.” Follow-up timeout 20.118 s; initial timeout 24.990 s.
No production settings changed. Evidence: `logs/conversation-recheck/REPORT.md`.

### E20 — backend available again; acoustic retest (2026-10-21)

Same E18 fixtures. Ten prompts played, nine spoken replies, no quota message.
Recorded Computer 4/4; synthetic 0/3. Short Add three follow-up missed with
no speech-start event; home and location sessions each completed four turns.
Home/weather now returned answers (actual device state not independently
verified); rooms reply was ambiguous Bedroom: bedroom. Boston context and
news topic switch worked. ASR 2.66–3.16 s; backend 2.66–32.32 s; reply prep
0.09–0.60 s. Follow-up timeout ~20 s; initial 24.991 s. No runtime changes.
Evidence: `logs/conversation-retest/REPORT.md`.

### E21 — permanent Echo startup and reconnect (2026-10-21)

Installed approved boot service and narrow SELinux init transition with current
patched binary and personalized models. Reboot now starts custom satellite,
suppresses Alexa, and joins saved the saved Wi-Fi network. Found stale idle Pi socket
after power loss; added TCP keepalive. Verified automatic reconnect across
Echo reboot with same Pi PID, both trained model hashes logged at 22:15:45.
No acoustic conversation test in this round. See E12-ECHO-DOT-ASSIST.md and
logs/echo-persistent-20261021 for verification and rollback details.
