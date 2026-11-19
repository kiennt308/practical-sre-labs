#!/usr/bin/env python3
"""Fit Neil Gunther's USL and Little's Law on OrderFlow capacity data.

Author: Kien Nguyen | License: Apache-2.0
Repo: https://github.com/kiennt308/practical-sre-labs
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

DEFAULT_CSV = (
    Path(__file__).resolve().parent / "02-usl-capacity-dataset.csv"
)


def load_dataset(csv_path: Path) -> list[tuple[int, float, float]]:
    """Read concurrency_n, throughput_rps, p95_ms rows."""
    rows: list[tuple[int, float, float]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                (
                    int(row["concurrency_n"]),
                    float(row["throughput_rps"]),
                    float(row["p95_ms"]),
                )
            )
    return rows


def usl_predict(
    n: float, gamma: float, alpha: float, beta: float
) -> float:
    """Evaluate C(N) = gamma * N / (1 + alpha*(N-1) + beta*N*(N-1))."""
    denom = 1.0 + alpha * (n - 1.0) + beta * n * (n - 1.0)
    return (gamma * n) / denom if denom > 0.0 else 0.0


def solve_linear_ab(
    rows: list[tuple[int, float, float]], gamma: float
) -> tuple[float, float]:
    """Solve 2x2 least squares for (alpha, beta) at fixed gamma."""
    s11 = s12 = s22 = b1 = b2 = 0.0
    for n, x_obs, _ in rows:
        if n <= 1 or x_obs <= 0.0:
            continue
        x1 = float(n - 1)
        x2 = float(n * (n - 1))
        y = (gamma * n / x_obs) - 1.0
        s11 += x1 * x1
        s12 += x1 * x2
        s22 += x2 * x2
        b1 += x1 * y
        b2 += x2 * y
    det = s11 * s22 - s12 * s12
    if abs(det) < 1e-12:
        return 0.0, 0.0
    alpha = max(0.0, (b1 * s22 - b2 * s12) / det)
    beta = max(0.0, (s11 * b2 - s12 * b1) / det)
    return alpha, beta


def sse_score(
    rows: list[tuple[int, float, float]],
    gamma: float,
    alpha: float,
    beta: float,
) -> float:
    """Compute throughput sum of squared errors."""
    return sum(
        (x_obs - usl_predict(float(n), gamma, alpha, beta)) ** 2
        for n, x_obs, _ in rows
    )


def fit_usl(
    rows: list[tuple[int, float, float]],
) -> tuple[float, float, float, float]:
    """Fit (gamma, alpha, beta, r2) via grid and coordinate search."""
    x1_guess = rows[0][1]
    best = (x1_guess, 0.02, 0.001, float("inf"))
    for step in range(-50, 51):
        g_try = x1_guess * (1.0 + step * 0.002)
        a_try, b_try = solve_linear_ab(rows, g_try)
        err = sse_score(rows, g_try, a_try, b_try)
        if err < best[3]:
            best = (g_try, a_try, b_try, err)

    g, a, b, best_err = best
    steps = [0.2, 0.002, 0.0001]
    for _ in range(40):
        for idx, delta in enumerate(steps):
            for sign in (-1.0, 1.0):
                cand = [g, a, b]
                cand[idx] = max(0.0, cand[idx] + sign * delta)
                err = sse_score(rows, cand[0], cand[1], cand[2])
                if err < best_err:
                    g, a, b, best_err = cand[0], cand[1], cand[2], err
        steps = [s * 0.7 for s in steps]

    mean_x = sum(r[1] for r in rows) / len(rows)
    sst = sum((r[1] - mean_x) ** 2 for r in rows)
    r2 = 1.0 - (best_err / sst) if sst > 0 else 1.0
    return g, a, b, r2


def print_report(rows: list[tuple[int, float, float]]) -> None:
    """Print Little's Law check, USL fit, and N+2 regional headroom."""
    gamma, alpha, beta, r2 = fit_usl(rows)
    n_max = math.sqrt((1.0 - alpha) / beta) if beta > 0 else float("inf")
    x_max = usl_predict(n_max, gamma, alpha, beta)
    safe_rps = 0.80 * x_max

    print("=== Little's Law & Observed Saturation Check ===")
    hdr = f"{'N':>4} {'RPS':>7} {'USL':>7} {'p95ms':>7} {'L=lamW':>7}"
    print(hdr)
    for n, rps, p95_ms in rows:
        pred = usl_predict(float(n), gamma, alpha, beta)
        l_est = rps * (p95_ms / 1000.0)
        line = (
            f"{n:>4} {rps:>7.1f} {pred:>7.1f} "
            f"{p95_ms:>7.1f} {l_est:>7.2f}"
        )
        print(line)

    print("\n=== Universal Scalability Law (USL) Fit ===")
    print(f"Base throughput gamma (X1) : {gamma:.2f} RPS")
    print(f"Contention (alpha / sigma) : {alpha:.5f}")
    print(f"Coherency  (beta  / kappa) : {beta:.6f}")
    print(f"Goodness of fit (R^2)      : {r2:.5f}")
    print(f"Peak concurrency (N_max)   : {n_max:.1f}")
    print(f"Max sustainable RPS        : {x_max:.1f} RPS")
    print(f"Safe 80% ceiling RPS       : {safe_rps:.1f} RPS")

    # Regional N+2 AZ headroom across us-east-1 & eu-west-1 (3 AZs each).
    # Each region must sustain peak demand with 1 AZ lost + 1 node drain.
    print("\n=== N+2 AZ Capacity Plan (us-east-1 & eu-west-1) ===")
    for region, peak_rps in (("us-east-1", 760.0), ("eu-west-1", 540.0)):
        min_pods = math.ceil(peak_rps / safe_rps)
        n_plus_2 = min_pods + 2
        per_az = math.ceil(n_plus_2 / 3)
        provisioned = per_az * 3
        print(
            f"{region}: peak={peak_rps:.0f} RPS -> min={min_pods} "
            f"-> N+2={n_plus_2} pods ({per_az}/AZ x 3={provisioned})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="USL & Little Law")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()
    rows = load_dataset(args.csv)
    print_report(rows)


if __name__ == "__main__":
    main()
