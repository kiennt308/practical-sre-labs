#!/usr/bin/env python3
"""Mixed-workload driver comparing naive vs protected retry hygiene.

Author: Kien Nguyen | License: Apache-2.0
Repo: https://github.com/kiennt308/practical-sre-labs
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
import urllib.error
import urllib.request

CLIENT_TIMEOUT_SEC = 0.46
RETRY_BUDGET_RATIO = 0.20
BASE_BACKOFF_SEC = 0.12
MAX_BACKOFF_SEC = 0.30


def fetch_downstream_calls(stats_url: str, base_url: str) -> int:
    """Query total downstream hits from stub /stats or app /metrics."""
    if stats_url:
        with urllib.request.urlopen(stats_url, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return int(data.get("downstream_calls", 0))
    metrics_url = base_url.rstrip("/") + "/metrics"
    with urllib.request.urlopen(metrics_url, timeout=2.0) as resp:
        for line in resp.read().decode("utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] == "downstream_calls":
                return int(parts[1])
    return 0


def post_once(url: str) -> tuple[int, float]:
    """Send a single POST request and return (status_code, ms)."""
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=CLIENT_TIMEOUT_SEC) as r:
            r.read()
            return r.status, (time.monotonic() - t0) * 1000.0
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, (time.monotonic() - t0) * 1000.0
    except (urllib.error.URLError, TimeoutError, OSError):
        return 599, (time.monotonic() - t0) * 1000.0


class RetryBudget:
    """Thread-safe 20% retry budget tracker."""

    def __init__(self, ratio: float) -> None:
        self._lock = threading.Lock()
        self._ratio = ratio
        self._attempts = 0
        self._retries = 0

    def record_initial(self) -> None:
        with self._lock:
            self._attempts += 1

    def try_consume_retry(self) -> bool:
        with self._lock:
            self._attempts += 1
            if (self._retries + 1) <= self._ratio * self._attempts:
                self._retries += 1
                return True
            return False


def percentile(values: list[float], pct: float) -> float:
    """Compute linear-nearest percentile in milliseconds."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return ordered[idx]


def run_load(
    base_url: str, mode: str, workers: int, duration: float
) -> dict[str, object]:
    """Execute concurrent workload and aggregate outcome metrics."""
    stop_at = time.monotonic() + duration
    lock = threading.Lock()
    budget = RetryBudget(RETRY_BUDGET_RATIO)
    stats = {
        "checkout_total": 0,
        "checkout_ok": 0,
        "recs_total": 0,
        "recs_shed": 0,
        "latencies_ms": [],
    }

    def worker(wid: int) -> None:
        rng = random.Random(1000 + wid)
        time.sleep(rng.uniform(0.0, 0.50))
        while time.monotonic() < stop_at:
            tick = time.monotonic()
            is_checkout = rng.random() < 0.70
            path = (
                "/v1/checkout" if is_checkout else "/v1/recommendations"
            )
            target = base_url.rstrip("/") + path
            budget.record_initial()
            code, ms = post_once(target)

            if mode == "naive":
                attempt = 0
                while code >= 500 and attempt < 4:
                    attempt += 1
                    time.sleep(0.020)
                    if time.monotonic() >= stop_at:
                        break
                    code, ms = post_once(target)
            else:
                if is_checkout:
                    attempt = 0
                    while code >= 500 and attempt < 2:
                        if not budget.try_consume_retry():
                            break
                        raw_cap = BASE_BACKOFF_SEC * (2**attempt)
                        cap = min(MAX_BACKOFF_SEC, raw_cap)
                        time.sleep(rng.uniform(0.0, cap))
                        attempt += 1
                        if time.monotonic() >= stop_at:
                            break
                        code, ms = post_once(target)

            with lock:
                stats["latencies_ms"].append(ms)
                if is_checkout:
                    stats["checkout_total"] += 1
                    if 200 <= code < 300:
                        stats["checkout_ok"] += 1
                else:
                    stats["recs_total"] += 1
                    if code == 503:
                        stats["recs_shed"] += 1

            elapsed = time.monotonic() - tick
            target_gap = rng.uniform(0.55, 0.69)
            if elapsed < target_gap:
                time.sleep(target_gap - elapsed)

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry storm driver")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--downstream-stats", default="")
    parser.add_argument(
        "--mode", choices=["naive", "protected"], default="naive"
    )
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--duration", type=float, default=6.0)
    args = parser.parse_args()

    before_hits = fetch_downstream_calls(args.downstream_stats, args.url)
    res = run_load(args.url, args.mode, args.workers, args.duration)
    after_hits = fetch_downstream_calls(args.downstream_stats, args.url)

    logical = res["checkout_total"] + res["recs_total"]
    downstream_hits = max(0, after_hits - before_hits)
    amp = downstream_hits / logical if logical else 0.0
    chk_pct = (
        100.0 * res["checkout_ok"] / res["checkout_total"]
        if res["checkout_total"]
        else 0.0
    )
    shed_pct = (
        100.0 * res["recs_shed"] / res["recs_total"]
        if res["recs_total"]
        else 0.0
    )
    p95_ms = percentile(res["latencies_ms"], 0.95)

    print(f"=== Retry Storm Report ({args.mode}) ===")
    print(f"Logical requests     : {logical}")
    print(f"Checkout OK %        : {chk_pct:.1f}%")
    print(f"Recs shed (503) %    : {shed_pct:.1f}%")
    print(f"Downstream hits      : {downstream_hits}")
    print(f"Amplification ratio  : {amp:.2f}x")
    print(f"p95 latency (ms)     : {p95_ms:.1f}")


if __name__ == "__main__":
    main()
