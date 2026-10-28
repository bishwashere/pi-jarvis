"""Exercise launcher routing with fake process/audio boundaries."""
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize('args,filename,lines', [
    ([], 'jarvis_voice.log', '80'),
    (['12'], 'jarvis_voice.log', '12'),
    (['echo-1'], 'devices/echo-1.log', '80'),
    (['echo-2', '25'], 'devices/echo-2.log', '25'),
])
def test_log_viewer_combined_default_and_device_selection(tmp_path, args, filename, lines):
    tools = tmp_path / 'tools'; tools.mkdir()
    tail = tools / 'tail'
    tail.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    tail.chmod(0o755)
    log = tmp_path / 'logs' / filename
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text('existing events\n')
    env = dict(os.environ, JARVIS_PROJECT_DIR=str(tmp_path), PATH=str(tools)+':'+os.environ['PATH'])
    result = subprocess.run(['bash', str(Path(__file__).resolve().parents[1]/'bin/jarvis'), 'logs', *args],
                            env=env, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == ['-n', lines, '-F', str(log)]
    assert log.read_text() == 'existing events\n'


@pytest.mark.parametrize('args', [['../echo-1'], ['echo-1', '-4'], ['80', 'extra'], ['echo-1', '80', 'extra']])
def test_log_viewer_rejects_invalid_arguments(tmp_path, args):
    log = tmp_path/'logs/devices/echo-1.log';log.parent.mkdir(parents=True);log.touch()
    result = subprocess.run(['bash', str(Path(__file__).resolve().parents[1]/'bin/jarvis'), 'logs', *args],
                            env=dict(os.environ, JARVIS_PROJECT_DIR=str(tmp_path)), capture_output=True, timeout=3)
    assert result.returncode == 2


@pytest.mark.parametrize('configured,override,expected', [
    ('', None, 'jarvis_voice.py'),
    ('192.0.2.1', None, 'hassmic_jarvis.py'),
    ('192.0.2.1', '', 'jarvis_voice.py'),
    ('', '192.0.2.2', 'hassmic_jarvis.py'),
])
@pytest.mark.parametrize('registry_path', ['', 'devices.json'])
def test_pi_launcher_routes_and_preserves_overrides(tmp_path, configured, override, expected, registry_path):
    root = Path(__file__).resolve().parents[1]
    project = tmp_path / 'project'
    tools = tmp_path / 'tools'
    venv = project / 'runtime/venv/bin'
    venv.mkdir(parents=True)
    tools.mkdir()
    (project / '.env').write_text(f'JARVIS_HASSMIC_HOST={configured}\nJARVIS_ECHO_DEVICES_PATH={registry_path}\n')
    python = venv / 'python'
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$1" "$JARVIS_HASSMIC_HOST"\n')
    python.chmod(0o755)
    flock = tools / 'flock'
    flock.write_text('#!/bin/sh\nshift 3\nexec "$@"\n')
    flock.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith('JARVIS_')}
    env.update(JARVIS_PROJECT_DIR=str(project), JARVIS_FOREGROUND='1', PATH=str(tools) + ':' + env['PATH'])
    if override is not None:
        env['JARVIS_HASSMIC_HOST'] = override
    result = subprocess.run(['bash', str(root / 'run_jarvis.sh')], cwd=tmp_path,
                            env=env, text=True, capture_output=True, check=True)
    lines = result.stdout.splitlines()
    assert lines[0] == str(project / ('hassmic_jarvis.py' if registry_path else expected))
    assert lines[1] == (configured if override is None else override)


def test_management_restart_and_current_log(tmp_path):
    import shutil
    import sys
    if not shutil.which('pgrep') or not shutil.which('ps') or not shutil.which('flock'):
        pytest.skip('Requires POSIX process tools and flock')
    try:
        visible = subprocess.run(['ps', '-p', str(os.getpid())], capture_output=True).returncode == 0
    except PermissionError:
        visible = False
    if not visible:
        pytest.skip('Process inspection is unavailable in this sandbox')
    root = Path(__file__).resolve().parents[1]
    project = tmp_path / 'managed'
    (project / 'logs').mkdir(parents=True)
    (project / 'logs/jarvis_voice.log').write_text('historical failure\n')
    script = project / 'jarvis_voice.py'
    script.write_text('import time\nprint("current runtime ready", flush=True)\ntime.sleep(60)\n')
    runner = project / 'run_jarvis.sh'
    runner.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n')
    runner.chmod(0o755)
    env = dict(os.environ, JARVIS_PROJECT_DIR=str(project))
    def manage(action):
        return subprocess.run(['bash', str(root / 'bin/jarvis'), action],
                              env=env, capture_output=True, text=True, timeout=15)
    try:
        for _ in range(2):
            result = manage('restart')
            assert result.returncode == 0, result.stdout + result.stderr
            assert 'Jarvis is running:' in result.stdout
            assert (project / 'logs/jarvis_voice.log').read_text() == 'current runtime ready\n'
        # Independent terminals may issue restart at the same time. Both
        # must succeed, with a live runtime after the last one finishes.
        concurrent = [subprocess.Popen(['bash', str(root / 'bin/jarvis'), 'restart'],
                      env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                      for _ in range(2)]
        for proc in concurrent:
            stdout, stderr = proc.communicate(timeout=15)
            assert proc.returncode == 0, stdout + stderr
        assert manage('status').returncode == 0
        assert any('historical failure' in p.read_text() for p in (project / 'logs/archive').iterdir())
        assert manage('stop').returncode == 0
        assert manage('status').returncode == 1
        runner.write_text('#!/bin/sh\necho startup-error >&2\nexit 3\n')
        result = manage('start')
        assert result.returncode == 1
        assert 'startup-error' in result.stdout
        assert 'failed to start' in result.stdout
    finally:
        manage('stop')


def test_log_viewer_follows_replaced_file(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    import time
    from pathlib import Path
    import pytest
    if sys.platform != 'linux':
        pytest.skip('Pi GNU tail rotation behavior')
    logs = tmp_path/'logs'; logs.mkdir()
    current = logs/'jarvis_voice.log'; current.write_text('before\n')
    output = tmp_path/'viewer.log'
    environment = dict(os.environ, JARVIS_PROJECT_DIR=str(tmp_path))
    launcher = Path(__file__).resolve().parents[1]/'bin/jarvis'
    with output.open('w') as stream:
        proc = subprocess.Popen(['bash', str(launcher), 'logs', '0'], env=environment,
                                stdout=stream, stderr=stream, start_new_session=True)
        try:
            time.sleep(.5)
            current.rename(logs/'previous.log')
            current.write_text('after-restart\n')
            deadline = time.monotonic()+10
            while time.monotonic()<deadline and 'after-restart' not in output.read_text():
                time.sleep(.1)
            assert 'after-restart' in output.read_text()
            assert 'before' not in output.read_text()
        finally:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
