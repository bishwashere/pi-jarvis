import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from config import (
    COMMAND_SERVER_HOST, COMMAND_SERVER_PORT, COMMAND_SERVER_TOKEN,
    COMMAND_SERVER_MAX_BODY_BYTES, COMMAND_SERVER_READ_TIMEOUT,
    COMMAND_SERVER_MAX_CONNECTIONS,
)
from voice_log import voice_event


def _authorized(headers) -> bool:
    if not COMMAND_SERVER_TOKEN:
        return True

    if len(headers.get_all("Authorization", [])) > 1 or len(headers.get_all("X-Jarvis-Token", [])) > 1:
        return False
    bearer = headers.get("Authorization", "")
    if hmac.compare_digest(bearer.encode(), f"Bearer {COMMAND_SERVER_TOKEN}".encode()):
        return True

    return hmac.compare_digest(headers.get("X-Jarvis-Token", "").encode(), COMMAND_SERVER_TOKEN.encode())


class _CommandHTTPServer(ThreadingHTTPServer):
    """Bound worker creation even when unauthenticated clients hold sockets open."""

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(COMMAND_SERVER_MAX_CONNECTIONS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def start_command_server(command_handler):
    if COMMAND_SERVER_HOST not in {"127.0.0.1", "localhost"} and not COMMAND_SERVER_TOKEN:
        raise RuntimeError(
            "JARVIS_COMMAND_SERVER_TOKEN is required when binding the command server outside localhost"
        )

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(COMMAND_SERVER_READ_TIMEOUT)
            super().setup()

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

            if self.headers.get("Transfer-Encoding") is not None:
                self.send_json(400, {"ok": False, "error": "Transfer-Encoding is not supported"})
                return
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                self.send_json(400, {"ok": False, "error": "A single nonnegative Content-Length is required"})
                return
            # Compare digit count first so enormous integer strings cannot cause work or errors.
            normalized = lengths[0].lstrip("0") or "0"
            if len(normalized) > len(str(COMMAND_SERVER_MAX_BODY_BYTES)) or int(normalized) > COMMAND_SERVER_MAX_BODY_BYTES:
                self.send_json(413, {"ok": False, "error": "Request body too large"})
                return
            length = int(normalized)

            try:
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("Incomplete body")
                raw = body.decode("utf-8") if length else "{}"
                payload = json.loads(raw) if raw.strip() else {}
                if not isinstance(payload, dict):
                    raise ValueError("JSON payload must be an object")
            except TimeoutError:
                self.send_json(408, {"ok": False, "error": "Request body timed out"})
                return
            except (ValueError, RecursionError):
                self.send_json(400, {"ok": False, "error": "Invalid JSON request body"})
                return

            try:
                result = command_handler(payload)
                status = 200 if result.get("ok", True) else 400
                self.send_json(status, result)
            except Exception as e:
                voice_event("command_server_error", error=e)
                self.send_json(500, {"ok": False, "error": "Command failed"})

    server = _CommandHTTPServer((COMMAND_SERVER_HOST, COMMAND_SERVER_PORT), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    voice_event(
        "command_server_started",
        host=COMMAND_SERVER_HOST,
        port=COMMAND_SERVER_PORT,
        token_required=bool(COMMAND_SERVER_TOKEN),
    )
    return server
