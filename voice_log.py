from datetime import datetime


def _format_value(value) -> str:
    text = str(value).replace("\n", " ").strip()
    if len(text) > 140:
        text = text[:137] + "..."
    return repr(text)


def voice_event(event: str, **fields):
    timestamp = datetime.now().isoformat(timespec="seconds")
    parts = [f"[{timestamp}] Voice event: {event}"]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    print(" ".join(parts), flush=True)
