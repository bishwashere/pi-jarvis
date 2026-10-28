from datetime import datetime
from contextlib import contextmanager
from contextvars import ContextVar
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from device_context import device_id


_event_handler = ContextVar('device_event_handler', default=None)


@contextmanager
def device_event_log(path, *, max_bytes, backup_count):
    """Append worker events to its own bounded log, including copied contexts."""
    handler = None
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=max_bytes,
                                      backupCount=backup_count, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
    except OSError as exc:
        # A logging destination must not take a voice device offline.
        voice_event('device_log_unavailable', path=path, error=exc)
    token = _event_handler.set(handler)
    try:
        yield
    finally:
        _event_handler.reset(token)
        if handler:
            handler.close()


def _format_value(value) -> str:
    text = str(value).replace("\n", " ").strip()
    if len(text) > 140:
        text = text[:137] + "..."
    return repr(text)


def voice_event(event: str, **fields):
    identifier = device_id()
    if identifier is not None:
        fields.setdefault('device_id', identifier)
    timestamp = datetime.now().isoformat(timespec="milliseconds")
    parts = [f"[{timestamp}] Voice event: {event}"]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    line = " ".join(parts)
    print(line, flush=True)
    handler = _event_handler.get()
    if handler:
        handler.handle(logging.LogRecord('jarvis.voice', logging.INFO,
                                         __file__, 0, line, (), None))
