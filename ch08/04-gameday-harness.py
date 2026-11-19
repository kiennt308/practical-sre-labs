#!/usr/bin/env python3
"""Automated Game Day runner with SLO steady-state probe & abort guard.

Author: Kien Nguyen | License: Apache-2.0
Repo: https://github.com/kiennt308/practical-sre-labs
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

TOXIC_NAME = "gameday_latency_350ms"


def api_request(
    url: str, method: str = "GET", payload: dict | None = None
) -> tuple[int, dict]:
    """Call Toxiproxy HTTP control API and return (status, json)."""
    data = json.dumps(payload).encode("utf-8") if payload else None
    headers = {"Content-Type": "application/json"} if payload else {}
    req = urllib.request.Request(
        url, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, {"error": body}


def inject_latency_toxic(api: str, proxy: str, latency_ms: int) -> None:
    """Attach latency toxic on Toxiproxy proxy."""
    url = f"{api.rstrip('/')}/proxies/{proxy}/toxics"
    payload = {
        "name": TOXIC_NAME,
        "type": "latency",
        "stream": "downstream",
        "toxicity": 1.0,
        "attributes": {"latency": latency_ms, "jitter": 20},
    }
    code, body = api_request(url, method="POST", payload=payload)
    if code not in (200, 201):
        raise RuntimeError(f"Failed to inject toxic: {code} {body}")


def delete_latency_toxic(api: str, proxy: str) -> None:
    """Remove latency toxic safely (ignore 404 if already gone)."""
    url = f"{api.rstrip('/')}/proxies/{proxy}/toxics/{TOXIC_NAME}"
    code, _ = api_request(url, method="DELETE")
    if code not in (200, 204, 404):
        raise RuntimeError(f"Failed to delete toxic: HTTP {code}")


def probe_once(
    target_url: str, timeout_sec: float = 1.5
) -> tuple[bool, float]:
    """Probe checkout endpoint once and return (ok, latency_ms)."""
    req = urllib.request.Request(
        target_url,
        data=b'{"order_id":"gameday-probe"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            resp.read()
            ms = (time.monotonic() - t0) * 1000.0
            return (200 <= resp.status < 300), ms
    except (urllib.error.URLError, TimeoutError, OSError):
        return False, (time.monotonic() - t0) * 1000.0


def probe_window(
    target_url: str, count: int, interval_sec: float = 0.05
) -> tuple[float, float]:
    """Measure (success_pct, p95_ms) across count probes."""
    ok_count = 0
    latencies: list[float] = []
    for _ in range(count):
        ok, ms = probe_once(target_url)
        if ok:
            ok_count += 1
        latencies.append(ms)
        time.sleep(interval_sec)
    ordered = sorted(latencies)
    idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return (100.0 * ok_count / count), ordered[idx]


def slo_passes(ok_pct: float, p95_ms: float, max_p95: float) -> bool:
    """Evaluate steady-state SLO (>= 99% success and p95 < threshold)."""
    return ok_pct >= 99.0 and p95_ms < max_p95


def main() -> int:
    parser = argparse.ArgumentParser(description="Game Day runner")
    parser.add_argument(
        "--toxiproxy-api", default="http://127.0.0.1:8474"
    )
    parser.add_argument("--proxy-name", default="payment")
    parser.add_argument(
        "--target-url", default="http://127.0.0.1:8080/v1/checkout"
    )
    parser.add_argument("--slo-p95-ms", type=float, default=250.0)
    args = parser.parse_args()

    print("[Step 1/5] Checking steady-state SLO baseline...")
    ok_pct, p95 = probe_window(args.target_url, count=15)
    print(f"  Baseline: success={ok_pct:.1f}% p95={p95:.1f}ms")
    if not slo_passes(ok_pct, p95, args.slo_p95_ms):
        print("ABORT BEFORE INJECTION: steady-state SLO unhealthy.")
        return 1

    aborted = False
    try:
        print("[Step 2/5] Injecting 350ms latency toxic...")
        inject_latency_toxic(args.toxiproxy_api, args.proxy_name, 350)

        print("[Step 3/5] Monitoring sliding window for SLO breach...")
        for win in range(1, 6):
            ok_pct, p95 = probe_window(args.target_url, count=8)
            msg = f"  Win {win}: ok={ok_pct:.1f}% p95={p95:.1f}ms"
            print(msg)
            if not slo_passes(ok_pct, p95, args.slo_p95_ms):
                print("  -> ABORT CONDITION TRIGGERED: SLO breached!")
                aborted = True
                break
    finally:
        print("[Step 4/5] Removing Toxiproxy toxic immediately...")
        delete_latency_toxic(args.toxiproxy_api, args.proxy_name)

    if not aborted:
        print("WARN: Fault did not breach SLO within monitor windows.")

    print("[Step 5/5] Verifying steady-state recovery...")
    time.sleep(0.2)
    rec_ok, rec_p95 = probe_window(args.target_url, count=15)
    print(f"  Recovery: success={rec_ok:.1f}% p95={rec_p95:.1f}ms")
    if not slo_passes(rec_ok, rec_p95, args.slo_p95_ms):
        print("FAIL: System failed to recover within SLO.")
        return 2

    print("PASS: Game Day steady-state -> abort -> recovery verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
