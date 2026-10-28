from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from types import SimpleNamespace

from device_context import bind_device
from voice_log import device_event_log, voice_event


def test_parallel_echo_logs_keep_combined_output_and_copied_context(tmp_path, capsys):
    def worker(number):
        with bind_device(SimpleNamespace(device_id=f'echo-{number}')):
            with device_event_log(tmp_path / f'echo-{number}.log', max_bytes=10000, backup_count=2):
                voice_event('wake_heard')
                with ThreadPoolExecutor(max_workers=1) as upload:
                    upload.submit(copy_context().run, voice_event, 'streaming_input_committed',
                                  text=f'command {number}').result()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(worker, (1, 2)))
    voice_event('shared_server_event')
    combined = capsys.readouterr().out
    for number in (1, 2):
        separate = (tmp_path / f'echo-{number}.log').read_text()
        assert 'wake_heard' in separate and 'streaming_input_committed' in separate
        assert f"device_id='echo-{number}'" in separate
        assert f"device_id='echo-{3-number}'" not in separate
        assert 'shared_server_event' not in separate
        assert all(line in combined for line in separate.splitlines())
    assert 'shared_server_event' in combined


def test_device_log_appends_across_restarts_and_rotates(tmp_path):
    path = tmp_path / 'echo-1.log'
    for event in ('before_restart', 'after_restart'):
        with device_event_log(path, max_bytes=1000, backup_count=2):
            voice_event(event)
    assert 'before_restart' in path.read_text() and 'after_restart' in path.read_text()
    with device_event_log(path, max_bytes=180, backup_count=2):
        for number in range(20):
            voice_event('event', number=number, detail='x' * 60)
    assert "number='19'" in path.read_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ['echo-1.log', 'echo-1.log.1', 'echo-1.log.2']
    assert all(p.stat().st_size <= 180 for p in tmp_path.iterdir())


def test_unwritable_log_does_not_stop_voice_events(tmp_path, capsys):
    obstacle = tmp_path / 'not-a-directory'
    obstacle.write_text('occupied')
    with device_event_log(obstacle / 'echo-1.log', max_bytes=1000, backup_count=2):
        voice_event('still_listening')
    output = capsys.readouterr().out
    assert 'device_log_unavailable' in output and 'still_listening' in output
