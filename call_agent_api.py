import json

import requests

from config import (
    API_HEALTH_URL,
    API_MODEL,
    API_URL,
    CONTINUE_LISTENING_DEFAULT,
    SYSTEM_PROMPT,
)


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
    response = requests.post(
        API_URL,
        headers={"Content-Type": "application/json"},
        json={
            "model": API_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
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
    return parse_agent_reply(content)


def check_agent_health() -> bool:
    response = requests.get(API_HEALTH_URL, timeout=5)
    response.raise_for_status()
    return True
