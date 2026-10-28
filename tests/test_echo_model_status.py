"""Loader snapshot regression: optional cached Echo source, no hardware/network."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_snapshot_only_reports_successfully_loaded_bytes(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source = root/'runtime/cache/echo-dot-assist/src/hassmic'
    model = root/'runtime/cache/e12-test/hey_jarvis.tflite'
    if not source.exists() or not model.exists() or not shutil.which('cc'):
        pytest.skip('Requires optional Echo source/model cache and C compiler')
    target = tmp_path/'src/hassmic'
    target.mkdir(parents=True)
    for name in ['wake_mww.c', 'mww.h', 'wake.h', 'mww_model.c', 'mww_features.c', 'hash.c', 'hash.h', 'proto_wyoming.c']:
        shutil.copy2(source/name, target/name)
    # The status patch follows the existing follow-up extension.
    subprocess.run(['patch', '-p1', '-i', str(root/'patches/echo-dot-assist-jarvis-followup.patch')], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(['patch', '-p1', '-i', str(root/'patches/echo-dot-assist-model-status.patch')], cwd=tmp_path, check=True, capture_output=True)
    shutil.copy2(model, tmp_path/'model.tflite')
    (tmp_path/'manifest.json').write_text('{}')
    harness = tmp_path/'test.c'
    harness.write_text(r'''
#include "src/hassmic/wake_mww.c"
#include <assert.h>
#include <unistd.h>
uint64_t wake_fed(void) { return 0; }
int mww_manifest_parse(const char *j, size_t n, struct mww_info *i, char *err, size_t cap) {
 memset(i, 0, sizeof *i); strcpy(i->name, "Hey \"Jarvis\""); i->cutoff=.97f; i->window=5; return 0;
}
int main(void) {
 char out[1400];
 mww_loaded_json(out,sizeof out); puts(out);
 assert(mww_open(0,"manifest.json",NULL)==0);
 unlink("model.tflite"); /* Snapshot must describe loaded bytes, not current disk. */
 mww_loaded_json(out,sizeof out); puts(out);
 mww_close(0); mww_loaded_json(out,sizeof out); puts(out);
 assert(mww_open(0,"manifest.json",NULL)<0);
 mww_loaded_json(out,sizeof out); puts(out);
 return 0;
}
''')
    binary = tmp_path/'test'
    subprocess.run(['cc', '-pthread', '-I', str(target), str(harness),
                    *[str(target/name) for name in ['mww_model.c', 'mww_features.c', 'hash.c']],
                    '-lm', '-o', str(binary)], check=True, capture_output=True)
    result = subprocess.run([str(binary)], cwd=tmp_path, check=True, capture_output=True, text=True)
    empty, loaded, closed, failed = map(json.loads, result.stdout.splitlines())
    assert empty == closed == failed == []
    assert loaded[0]['name'] == 'Hey "Jarvis"'
    assert loaded[0]['sha256'] == hashlib.sha256(model.read_bytes()).hexdigest()
    assert loaded[0]['cutoff'] == .97
