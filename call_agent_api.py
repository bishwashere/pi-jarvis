import json
from datetime import datetime

import requests

from config import (
    API_CONVERSATION_ID,
    API_HEALTH_URL,
    API_MODEL,
    API_URL,
    CONTINUE_LISTENING_DEFAULT,
)


def log_api_event(label: str, value):
    timestamp = datetime.now().isoformat(timespec="seconds")
    print(f"[{timestamp}] Pasture {label}: {value}", flush=True)


def parse_agent_reply(content: str) -> dict:
    """
    Supports both plain text and JSON responses.

    Plain text:
      "Here is the answer"

    JSON:
      {"reply": "Here is the answer", "continue_listening": true}
    """
    content = content.strip()

    try:
        parsed = json.loads(content)

        if isinstance(parsed, dict):
            reply = str(parsed.get("reply", "")).strip()
            continue_listening = bool(
                parsed.get("continue_listening", CONTINUE_LISTENING_DEFAULT)
            )

            return {
                "reply": reply or "I have no response.",
                "continue_listening": continue_listening,
            }

    except Exception:
        pass

    return {
        "reply": content,
        "continue_listening": CONTINUE_LISTENING_DEFAULT,
    }


def ask_pasture(user_text: str) -> dict:
    log_api_event(
        "request",
        {
            "model": API_MODEL,
            "conversation_id": API_CONVERSATION_ID,
            "user": user_text,
        },
    )

    response = requests.post(
        API_URL,
        headers={
            "Content-Type": "application/json",
            "X-Pasture-Conversation-Id": API_CONVERSATION_ID,
        },
        json={
            "model": API_MODEL,
            "conversation_id": API_CONVERSATION_ID,
            "messages": [
                {
                    "role": "user",
                    "content": user_text,
                },
            ],
        },
        timeout=60,
    )

    response.raise_for_status()
    data = response.json()

    content = data["choices"][0]["message"]["content"].strip()
    parsed = parse_agent_reply(content)
    log_api_event("response", {"raw": content, "parsed": parsed})
    return parsed


def start_new_pasture_session() -> bool:
    try:
        response = requests.post(
            API_URL,
            headers={
                "Content-Type": "application/json",
                "X-Pasture-Conversation-Id": API_CONVERSATION_ID,
            },
            json={
                "model": API_MODEL,
                "conversation_id": API_CONVERSATION_ID,
                "messages": [
                    {
                        "role": "user",
                        "content": "new session",
                    },
                ],
            },
            timeout=20,
        )
        response.raise_for_status()
        log_api_event(
            "session",
            {
                "conversation_id": API_CONVERSATION_ID,
                "status": "new session started",
            },
        )
        return True
    except Exception as e:
        log_api_event(
            "session",
            {
                "conversation_id": API_CONVERSATION_ID,
                "status": "new session failed",
                "error": str(e),
            },
        )
        return False


def check_agent_health() -> bool:
    response = requests.get(API_HEALTH_URL, timeout=5)
    response.raise_for_status()
    return True
