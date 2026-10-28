"""Host-side check of the Echo patch; does not claim ARM/hardware validation."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_echo_playback_waits_for_queue_before_close(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = root / 'runtime/cache/echo-dot-assist/src'
    if not source.exists() or not shutil.which('cc') or not shutil.which('patch'):
        pytest.skip('Requires optional pinned upstream source cache and host C tools')
    target = tmp_path / 'src/hassmic'
    target.mkdir(parents=True)
    for name in ('audio_mixer.c', 'audio.h'):
        shutil.copyfile(source / 'hassmic' / name, target / name)
    subprocess.run(['patch', '-p1', '-i', str(root / 'patches/echo-dot-assist-playback-drain.patch')],
                   cwd=tmp_path, check=True, capture_output=True)
    binary = tmp_path / 'check'
    subprocess.run(['cc', '-I', str(target), '-I', str(source / 'include'),
                    str(root / 'tests/hassmic_drain_harness.c'), '-lm', '-o', str(binary)],
                   check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)


def test_echo_followup_extension_calls_restart_before_playback_end(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = root/'runtime/cache/echo-dot-assist/src/hassmic'
    if not source.exists() or not shutil.which('cc') or not shutil.which('patch'):
        pytest.skip('Requires optional pinned upstream source cache and host C tools')
    target = tmp_path/'src/hassmic'
    target.mkdir(parents=True)
    for name in ('proto_wyoming.c', 'wyoming.c', 'wyoming.h', 'core.h', 'board.h'):
        shutil.copyfile(source/name, target/name)
    subprocess.run(['patch', '-p1', '-i', str(root/'patches/echo-dot-assist-jarvis-followup.patch')],
                   cwd=tmp_path, check=True, capture_output=True)
    harness = tmp_path/'harness.c'
    harness.write_text(r'''
#include <assert.h>
#include "src/hassmic/proto_wyoming.c"
pthread_mutex_t core_lock = PTHREAD_MUTEX_INITIALIZER;
int core_local_wake = 1, core_port = 16700;
const char *core_name = "Test Echo";
const struct board board = { .model = "Echo Dot 2" };
static int restarted, ended;
void core_restart_after(void) { assert(!ended); restarted++; }
void core_tts_end(void) { ended++; }
void core_tts_begin(unsigned r, unsigned c, int m) {}
void core_tts_data(const void *p, size_t n) {}
void core_link(int u, int r) {}
void core_set_state(enum state s) {}
enum state core_state(void) { return LISTENING; }
void core_mic_off(void) {}
void core_no_speech(void) {}
void core_error(void) {}
int main(void) {
 struct wy_event event = {0};
 strcpy(event.type, "audio-stop");
 strcpy(event.json, "{\"jarvis_followup\":1}");
 handle(&event);
 assert(restarted == 1 && ended == 1);
 restarted = ended = 0;
 strcpy(event.json, "{}");
 handle(&event);
 assert(restarted == 0 && ended == 1);
 return 0;
}
''')
    binary = tmp_path/'check'
    subprocess.run(['cc', '-pthread', '-I', str(target), str(harness), str(target/'wyoming.c'), '-o', str(binary)],
                   check=True, capture_output=True)
    subprocess.run([str(binary)], check=True, capture_output=True)
