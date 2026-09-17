import json
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from call_agent_api import ask_pasture_for_daily_context
from config import (
    DAILY_CONTEXT_ENABLED,
    DAILY_CONTEXT_MAX_SUGGESTIONS,
    DAILY_CONTEXT_MAX_UTTERANCES,
    DAILY_CONTEXT_MIN_UTTERANCES,
    DAILY_CONTEXT_PATH,
    DAILY_CONTEXT_REFRESH_SECONDS,
    DAILY_CONTEXT_WAKE_REPLY_PROBABILITY,
)


_refresh_lock = threading.Lock()
_refresh_running = False

AFFIRMATIVE_COMMANDS = {
    "yes",
    "yeah",
    "yep",
    "sure",
    "ok",
    "okay",
    "please",
    "go ahead",
    "do it",
    "that's fine",
    "sounds good",
}


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def empty_state(date: str | None = None) -> dict:
    return {
        "date": date or today_key(),
        "utterances": [],
        "suggestions": [],
        "last_refresh_ts": 0.0,
    }


def load_state(path: str = DAILY_CONTEXT_PATH) -> dict:
    state_path = Path(path)
    current_date = today_key()
    if not state_path.is_file():
        return empty_state(current_date)

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return empty_state(current_date)

    if not isinstance(data, dict) or data.get("date") != current_date:
        return empty_state(current_date)

    data.setdefault("utterances", [])
    data.setdefault("suggestions", [])
    data.setdefault("last_refresh_ts", 0.0)
    return data


def save_state(state: dict, path: str = DAILY_CONTEXT_PATH):
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def normalize_for_match(text: str) -> str:
    cleaned = text.lower().strip()
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
    return " ".join(cleaned.split())


def record_utterance(text: str, kind: str = "command"):
    if not DAILY_CONTEXT_ENABLED:
        return

    phrase = str(text or "").strip()
    if not phrase:
        return

    state = load_state()
    utterances = state.get("utterances", [])
    utterances.append(
        {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "kind": kind,
            "text": phrase,
        }
    )
    state["utterances"] = utterances[-DAILY_CONTEXT_MAX_UTTERANCES:]
    save_state(state)


def clean_suggestion(text: str) -> str:
    suggestion = str(text or "").strip()
    suggestion = re.sub(r"^\s*[-*\d.)]+\s*", "", suggestion)
    suggestion = suggestion.strip(" \"'`")
    suggestion = re.sub(r"\s+", " ", suggestion)
    return suggestion[:120].strip()


def parse_suggestions(content: str) -> list[str]:
    raw = str(content or "").strip()
    candidates = []

    def from_parsed(value):
        if isinstance(value, dict):
            return value.get("suggestions") or value.get("prompts") or []
        if isinstance(value, list):
            return value
        return []

    for json_text in [
        raw,
        raw[raw.find("{") : raw.rfind("}") + 1] if "{" in raw and "}" in raw else "",
        raw[raw.find("[") : raw.rfind("]") + 1] if "[" in raw and "]" in raw else "",
    ]:
        if not json_text:
            continue
        try:
            candidates = from_parsed(json.loads(json_text))
            if candidates:
                break
        except Exception:
            pass

    if not candidates:
        candidates = [line for line in raw.splitlines() if line.strip()]

    suggestions = []
    seen = set()
    for candidate in candidates:
        text = clean_suggestion(candidate)
        key = normalize_for_match(text)
        if not text or key in seen:
            continue
        if len(text.split()) > 14:
            continue
        seen.add(key)
        suggestions.append(text)
        if len(suggestions) >= DAILY_CONTEXT_MAX_SUGGESTIONS:
            break

    return suggestions


def build_refresh_prompt(utterances: list[dict]) -> str:
    recent = utterances[-20:]
    lines = "\n".join(
        f"- {item.get('text', '').strip()}" for item in recent if item.get("text")
    )
    return (
        "Internal Raspberry Pi Jarvis task. This is not a user-facing chat turn.\n"
        "From today's voice commands, create short optional wake prompts Jarvis may say later.\n"
        "Each prompt should be natural, spoken, and specific to likely unfinished context.\n"
        "Return JSON only: {\"suggestions\":[\"Do you still want to check the weather?\"]}.\n"
        "Use at most 6 suggestions, each under 12 words. Avoid generic help phrases.\n\n"
        f"Today's user voice commands:\n{lines}"
    )


def refresh_context_bucket():
    state = load_state()
    utterances = state.get("utterances", [])
    if len(utterances) < DAILY_CONTEXT_MIN_UTTERANCES:
        return

    prompt = build_refresh_prompt(utterances)
    try:
        content = ask_pasture_for_daily_context(prompt)
        suggestions = parse_suggestions(content)
    except Exception as e:
        print(f"Daily context refresh failed: {e}", flush=True)
        return

    current = load_state()
    if suggestions:
        current["suggestions"] = [{"text": text, "ts": time.time()} for text in suggestions]
    current["last_refresh_ts"] = time.time()
    save_state(current)
    if suggestions:
        print(f"Daily context suggestions refreshed: {suggestions}", flush=True)


def maybe_refresh_context_bucket_async():
    global _refresh_running

    if not DAILY_CONTEXT_ENABLED:
        return

    state = load_state()
    if len(state.get("utterances", [])) < DAILY_CONTEXT_MIN_UTTERANCES:
        return

    if time.time() - float(state.get("last_refresh_ts") or 0) < DAILY_CONTEXT_REFRESH_SECONDS:
        return

    with _refresh_lock:
        if _refresh_running:
            return
        _refresh_running = True

    def worker():
        global _refresh_running
        try:
            refresh_context_bucket()
        finally:
            with _refresh_lock:
                _refresh_running = False

    threading.Thread(target=worker, daemon=True).start()


def choose_wake_reply(default_replies: list[str]) -> tuple[str, str]:
    fallback = random.choice(default_replies)
    if not DAILY_CONTEXT_ENABLED:
        return fallback, "default"

    probability = max(0.0, min(1.0, DAILY_CONTEXT_WAKE_REPLY_PROBABILITY))
    if random.random() >= probability:
        return fallback, "default"

    state = load_state()
    suggestions = [
        str(item.get("text", "")).strip()
        for item in state.get("suggestions", [])
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    if not suggestions:
        return fallback, "default"

    return random.choice(suggestions), "daily-context"


def contextualize_affirmative_command(command: str, wake_prompt: str | None) -> str:
    if not wake_prompt:
        return command

    if normalize_for_match(command) not in AFFIRMATIVE_COMMANDS:
        return command

    return f"Yes. The wake prompt was: {wake_prompt}"
