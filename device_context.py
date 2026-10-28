"""Per-Echo identity for logs and API calls; never shared mutable turn state."""
from contextlib import contextmanager
from contextvars import ContextVar

from config import API_CONVERSATION_ID

_current = ContextVar('jarvis_device', default=None)


@contextmanager
def bind_device(device):
    token = _current.set(device)
    try:
        yield
    finally:
        _current.reset(token)


def device_id():
    device = _current.get()
    return device.device_id if device else None


def conversation_id():
    device = _current.get()
    return device.conversation_id if device else API_CONVERSATION_ID


def request_headers():
    identifier = device_id()
    return {'X-Pasture-Device-Id': identifier} if identifier else {}
