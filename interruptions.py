import concurrent.futures
import queue

from detect_wake_word import WakeWordMonitor
from listen_to_mic import audio_queue, clear_audio_queue, open_microphone_stream


class WakeWordInterrupted(Exception):
    """Raised when the wake word is heard during another operation."""


def wait_for_result_or_wake_word(callable_fn, model, *args, **kwargs):
    monitor = WakeWordMonitor(model)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(callable_fn, *args, **kwargs)

    try:
        clear_audio_queue()
        with open_microphone_stream():
            while True:
                try:
                    return future.result(timeout=0.2)
                except concurrent.futures.TimeoutError:
                    pass

                try:
                    data = audio_queue.get_nowait()
                except queue.Empty:
                    continue

                if monitor.accept_audio(data):
                    future.cancel()
                    raise WakeWordInterrupted()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
