#!/usr/bin/env python3
"""Payment worker stub for Toxiproxy overload and Game Day labs.

Author: Kien Nguyen | License: Apache-2.0
Repo: https://github.com/kiennt308/practical-sre-labs
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALL_LOCK = threading.Lock()
TOTAL_CALLS = 0


class PaymentStubServer(ThreadingHTTPServer):
    """Concurrent HTTP stub simulating downstream payment approval."""

    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


class PaymentStubHandler(BaseHTTPRequestHandler):
    """Handle POST /charge (10ms work) and GET /stats."""

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send_json(self, code: int, payload: dict[str, object]) -> None:
        body = (json.dumps(payload) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/stats":
            with CALL_LOCK:
                count = TOTAL_CALLS
            self._send_json(200, {"downstream_calls": count})
            return
        if self.path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        global TOTAL_CALLS
        length = int(self.headers.get("Content-Length", "0"))
        if length > 0:
            self.rfile.read(length)
        if self.path == "/charge":
            with CALL_LOCK:
                TOTAL_CALLS += 1
            time.sleep(0.010)
            self._send_json(200, {"approved": True})
            return
        self._send_json(404, {"error": "not_found"})


def main() -> None:
    server = PaymentStubServer(("0.0.0.0", 9090), PaymentStubHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
