import concurrent.futures
import queue
import time

from detect_wake_word import WakeWordMonitor
from listen_to_mic import audio_queue, clear_audio_queue, open_microphone_stream


class WakeWordInterrupted(Exception):
    """Raised when the wake word is heard during another operation."""


def wait_for_result_or_wake_word(
    callable_fn,
    model,
    *args,
    on_wait_start=None,
    on_wait_start_delay=0,
    on_still_waiting=None,
    on_still_waiting_delay=0,
    **kwargs,
):
    monitor = WakeWordMonitor(model)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(callable_fn, *args, **kwargs)

    try:
        started_at = time.time()
        wait_started = False
        wait_started_at = None
        still_waiting_started = False

        clear_audio_queue()
        with open_microphone_stream():
            while True:
                try:
                    return future.result(timeout=0.2)
                except concurrent.futures.TimeoutError:
                    pass

                if (
                    on_wait_start is not None
                    and not wait_started
                    and time.time() - started_at >= on_wait_start_delay
                    and not future.done()
                ):
                    wait_started = True
                    wait_started_at = time.time()
                    on_wait_start()

                if (
                    on_still_waiting is not None
                    and wait_started
                    and not still_waiting_started
                    and wait_started_at is not None
                    and time.time() - wait_started_at >= on_still_waiting_delay
                    and not future.done()
                ):
                    still_waiting_started = True
                    on_still_waiting()

                try:
                    data = audio_queue.get_nowait()
                except queue.Empty:
                    continue

                if monitor.accept_audio(data):
                    future.cancel()
                    raise WakeWordInterrupted()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
