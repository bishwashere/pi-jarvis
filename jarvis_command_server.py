import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import COMMAND_SERVER_HOST, COMMAND_SERVER_PORT, COMMAND_SERVER_TOKEN
from voice_log import voice_event


def _authorized(headers) -> bool:
    if not COMMAND_SERVER_TOKEN:
        return True

    bearer = headers.get("Authorization", "")
    if bearer == f"Bearer {COMMAND_SERVER_TOKEN}":
        return True

    return headers.get("X-Jarvis-Token", "") == COMMAND_SERVER_TOKEN


def start_command_server(command_handler):
    if COMMAND_SERVER_HOST not in {"127.0.0.1", "localhost"} and not COMMAND_SERVER_TOKEN:
        raise RuntimeError(
            "JARVIS_COMMAND_SERVER_TOKEN is required when binding the command server outside localhost"
        )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def send_json(self, status: int, payload: dict):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != "/health":
                self.send_json(404, {"ok": False, "error": "not found"})
                return

            self.send_json(200, {"ok": True, "service": "jarvis-command"})

        def do_POST(self):
            if self.path != "/command":
                self.send_json(404, {"ok": False, "error": "not found"})
                return

            if not _authorized(self.headers):
                voice_event("command_server_rejected", reason="unauthorized")
                self.send_json(401, {"ok": False, "error": "unauthorized"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0

            try:
                raw = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(raw) if raw.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("JSON payload must be an object")
            except Exception as e:
                self.send_json(400, {"ok": False, "error": str(e)})
                return

            try:
                result = command_handler(payload)
                status = 200 if result.get("ok", True) else 400
                self.send_json(status, result)
            except Exception as e:
                voice_event("command_server_error", error=e)
                self.send_json(500, {"ok": False, "error": str(e)})

    server = ThreadingHTTPServer((COMMAND_SERVER_HOST, COMMAND_SERVER_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    voice_event(
        "command_server_started",
        host=COMMAND_SERVER_HOST,
        port=COMMAND_SERVER_PORT,
        token_required=bool(COMMAND_SERVER_TOKEN),
    )
    return server
