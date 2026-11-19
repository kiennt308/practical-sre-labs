#!/usr/bin/env python3
"""OrderFlow checkout service demonstrating overload defense.

Author: Kien Nguyen | License: Apache-2.0
Repo: https://github.com/kiennt308/practical-sre-labs
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOWNSTREAM_URL = os.getenv(
    "DOWNSTREAM_URL", "http://127.0.0.1:8475/charge"
)
PROTECTED = os.getenv("PROTECTED", "0") == "1"
INITIAL_LIMIT = int(os.getenv("INITIAL_LIMIT", "12"))
DOWNSTREAM_TIMEOUT = float(os.getenv("DOWNSTREAM_TIMEOUT", "0.45"))
POOL_SIZE = int(os.getenv("POOL_SIZE", "10"))
NAIVE_TIMEOUT = 1.0
CB_ERR_THRESHOLD = 5
CB_COOLDOWN_SEC = 0.50

STATE_LOCK = threading.Lock()
POOL_SEM = threading.Semaphore(POOL_SIZE)
METRICS = {
    "requests_ok": 0,
    "requests_err": 0,
    "shed_503": 0,
    "downstream_calls": 0,
    "inflight": 0,
}
AIMD = {
    "limit": float(INITIAL_LIMIT),
    "min": 4.0,
    "max": float(max(INITIAL_LIMIT * 2, 16)),
    "consec_err": 0,
    "cb_open_until": 0.0,
}


def call_downstream(timeout_sec: float) -> tuple[bool, int]:
    """POST to payment-worker via Toxiproxy with hard timeout."""
    with STATE_LOCK:
        METRICS["downstream_calls"] += 1
    req = urllib.request.Request(
        DOWNSTREAM_URL,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            resp.read()
            return (200 <= resp.status < 300), resp.status
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, 504


def admit_protected(path: str) -> tuple[bool, str]:
    """Check circuit breaker, priority shed, and AIMD limit."""
    now = time.monotonic()
    with STATE_LOCK:
        if now < AIMD["cb_open_until"]:
            METRICS["shed_503"] += 1
            return False, "circuit_open"
        limit_val = int(AIMD["limit"])
        shed_at = int(0.65 * limit_val)
        inflight = METRICS["inflight"]
        if path == "/v1/recommendations" and inflight >= shed_at:
            METRICS["shed_503"] += 1
            return False, "low_priority_shed"
        if inflight >= limit_val:
            METRICS["shed_503"] += 1
            return False, "aimd_limit"
        METRICS["inflight"] += 1
        return True, "ok"


def record_aimd(ok: bool, elapsed: float) -> None:
    """Adjust AIMD concurrency limit and circuit state."""
    with STATE_LOCK:
        if ok:
            AIMD["consec_err"] = 0
            if AIMD["limit"] < INITIAL_LIMIT:
                rec = AIMD["limit"] + 0.25
                AIMD["limit"] = min(float(INITIAL_LIMIT), rec)
            elif elapsed < DOWNSTREAM_TIMEOUT * 0.25:
                AIMD["limit"] = min(AIMD["max"], AIMD["limit"] + 0.05)
            METRICS["requests_ok"] += 1
        else:
            AIMD["consec_err"] += 1
            AIMD["limit"] = max(AIMD["min"], AIMD["limit"] * 0.70)
            if AIMD["consec_err"] >= CB_ERR_THRESHOLD:
                AIMD["cb_open_until"] = time.monotonic() + CB_COOLDOWN_SEC
            METRICS["requests_err"] += 1


def handle_workload(path: str) -> tuple[int, dict[str, object]]:
    """Execute request in naive or overload-protected mode."""
    if PROTECTED:
        admitted, reason = admit_protected(path)
        if not admitted:
            return 503, {"status": "shed", "reason": reason}
        budget = DOWNSTREAM_TIMEOUT
    else:
        with STATE_LOCK:
            METRICS["inflight"] += 1
        budget = NAIVE_TIMEOUT

    start = time.monotonic()
    acquired = False
    ok = False
    try:
        acquired = POOL_SEM.acquire(timeout=budget)
        remaining = budget - (time.monotonic() - start)
        if acquired and remaining > 0.02:
            ok, _ = call_downstream(remaining)
    finally:
        if acquired:
            POOL_SEM.release()
        with STATE_LOCK:
            METRICS["inflight"] -= 1

    elapsed = time.monotonic() - start
    if PROTECTED:
        record_aimd(ok, elapsed)
    else:
        with STATE_LOCK:
            key = "requests_ok" if ok else "requests_err"
            METRICS[key] += 1

    if ok:
        return 200, {"status": "ok", "path": path}
    return 504, {"status": "error", "path": path}


class CheckoutServer(ThreadingHTTPServer):
    """HTTP server configured for concurrent overload labs."""

    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 128


class CheckoutHandler(BaseHTTPRequestHandler):
    """Serve health, metrics, checkout, and recommendations."""

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def _send_bytes(
        self,
        code: int,
        body: bytes,
        ctype: str,
        extra: dict | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_bytes(
                200, b'{"status":"ok"}\n', "application/json"
            )
            return
        if self.path == "/metrics":
            with STATE_LOCK:
                lines = [
                    f"requests_ok {METRICS['requests_ok']}",
                    f"requests_err {METRICS['requests_err']}",
                    f"shed_503 {METRICS['shed_503']}",
                    f"downstream_calls {METRICS['downstream_calls']}",
                    f"aimd_limit {int(AIMD['limit'])}",
                    f"inflight {METRICS['inflight']}",
                ]
            payload = ("\n".join(lines) + "\n").encode("utf-8")
            self._send_bytes(200, payload, "text/plain; charset=utf-8")
            return
        self._send_bytes(
            404, b'{"error":"not_found"}\n', "application/json"
        )

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 0:
            self.rfile.read(length)
        if self.path in ("/v1/checkout", "/v1/recommendations"):
            code, payload = handle_workload(self.path)
            headers = {"Retry-After": "1"} if code == 503 else None
            raw = (json.dumps(payload) + "\n").encode("utf-8")
            self._send_bytes(code, raw, "application/json", headers)
            return
        self._send_bytes(
            404, b'{"error":"not_found"}\n', "application/json"
        )


def main() -> None:
    server = CheckoutServer(("0.0.0.0", 8080), CheckoutHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
