import os
import requests

API_URL = os.environ.get("JARVIS_API_URL", "http://127.0.0.1:1234/v1/chat/completions")
MODEL = "api-assistant"

response = requests.post(
    API_URL,
    headers={"Content-Type": "application/json"},
    json={
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "Say hello in one short sentence."}
        ],
    },
    timeout=60,
)

response.raise_for_status()
data = response.json()

reply = data["choices"][0]["message"]["content"]
print(reply)
