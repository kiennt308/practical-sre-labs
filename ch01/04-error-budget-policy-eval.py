#!/usr/bin/env python3
"""Evaluate OrderFlow 30d error budget and DORA release gates.

Computes error budget consumption, remaining budget minutes, burn rate,
DORA Change Failure Rate (CFR) interaction, and release gate decisions
across healthy, warning, and exhausted scenarios using stdlib only.

Copyright (c) 2026 Kien Nguyen. Licensed under Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

SLO_TARGET = 0.9995
WINDOW_DAYS = 30
MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class Scenario:
    """Inputs representing a 30-day OrderFlow reliability snapshot."""

    name: str
    valid_requests: int
    bad_requests: int
    burn_rate_1h: float
    dora_cfr_pct: float
    deploys_last_7d: int


@dataclass(frozen=True)
class Evaluation:
    """Calculated error budget posture and release gate decision."""

    scenario: str
    budget_total_min: float
    consumed_pct: float
    remaining_pct: float
    remaining_min: float
    burn_rate_1h: float
    dora_cfr_pct: float
    deploys_last_7d: int
    decision: str
    rationale: str


def default_scenarios() -> list[Scenario]:
    """Return three deterministic OrderFlow operational scenarios."""
    return [
        Scenario(
            name="healthy",
            valid_requests=43_200_000,
            bad_requests=3_240,
            burn_rate_1h=0.4,
            dora_cfr_pct=4.2,
            deploys_last_7d=28,
        ),
        Scenario(
            name="warning",
            valid_requests=43_200_000,
            bad_requests=16_200,
            burn_rate_1h=3.2,
            dora_cfr_pct=11.5,
            deploys_last_7d=42,
        ),
        Scenario(
            name="exhausted",
            valid_requests=43_200_000,
            bad_requests=23_760,
            burn_rate_1h=14.8,
            dora_cfr_pct=24.0,
            deploys_last_7d=64,
        ),
    ]


def decide_gate(
    remaining_pct: float,
    burn_rate_1h: float,
    dora_cfr_pct: float,
) -> tuple[str, str]:
    """Combine error budget, burn rate, and DORA CFR into a gate."""
    if remaining_pct <= 0.0:
        return (
            "FREEZE_FEATURES",
            "30d error budget exhausted; freeze non-reliability deploys",
        )
    if burn_rate_1h >= 14.4:
        return (
            "FREEZE_FEATURES",
            "1h burn rate >= 14.4x; halt rollouts and mitigate incident",
        )
    if remaining_pct < 15.0 and dora_cfr_pct >= 15.0:
        return (
            "FREEZE_FEATURES",
            "Low budget (<15%) amplified by high DORA CFR (>=15%)",
        )
    if remaining_pct < 30.0 or burn_rate_1h >= 2.0 or dora_cfr_pct >= 10:
        return (
            "CANARY_ONLY",
            "Elevated burn or DORA CFR; restrict to canary/rollback",
        )
    return (
        "ALLOW",
        "Budget healthy and DORA CFR below 10%; normal delivery ok",
    )


def evaluate_scenario(sc: Scenario) -> Evaluation:
    """Compute budget minutes, remaining %, and gate for a scenario."""
    window_minutes = float(WINDOW_DAYS * MINUTES_PER_DAY)
    allowed_error_ratio = 1.0 - SLO_TARGET
    budget_total_min = round(window_minutes * allowed_error_ratio, 2)

    error_ratio = sc.bad_requests / sc.valid_requests
    consumed_pct = round((error_ratio / allowed_error_ratio) * 100.0, 2)
    remaining_pct = round(max(0.0, 100.0 - consumed_pct), 2)
    remaining_min = round(
        max(0.0, budget_total_min * (1.0 - consumed_pct / 100.0)),
        2,
    )
    decision, rationale = decide_gate(
        remaining_pct=remaining_pct,
        burn_rate_1h=sc.burn_rate_1h,
        dora_cfr_pct=sc.dora_cfr_pct,
    )
    return Evaluation(
        scenario=sc.name,
        budget_total_min=budget_total_min,
        consumed_pct=consumed_pct,
        remaining_pct=remaining_pct,
        remaining_min=remaining_min,
        burn_rate_1h=sc.burn_rate_1h,
        dora_cfr_pct=sc.dora_cfr_pct,
        deploys_last_7d=sc.deploys_last_7d,
        decision=decision,
        rationale=rationale,
    )


def print_table(results: list[Evaluation]) -> None:
    """Render a compact terminal report within 74-char line limits."""
    print("OrderFlow Checkout Error Budget Policy Report (99.95% / 30d)")
    print("-" * 72)
    for res in results:
        print(
            f"Scenario: {res.scenario.upper():<10} | "
            f"Gate: {res.decision}"
        )
        print(
            f"  Budget: {res.budget_total_min:.1f}m | "
            f"Consumed: {res.consumed_pct:6.2f}% | "
            f"Rem: {res.remaining_min:5.2f}m ({res.remaining_pct:5.2f}%)"
        )
        print(
            f"  1h Burn: {res.burn_rate_1h:5.1f}x | "
            f"DORA CFR: {res.dora_cfr_pct:4.1f}% | "
            f"7d Deploys: {res.deploys_last_7d}"
        )
        print(f"  Reason: {res.rationale}")
        print("-" * 72)


def main() -> int:
    """Parse arguments and run the OrderFlow policy evaluator."""
    parser = argparse.ArgumentParser(
        description="Evaluate OrderFlow 30d error budget policy."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit evaluation results as formatted JSON.",
    )
    args = parser.parse_args()

    results = [evaluate_scenario(sc) for sc in default_scenarios()]
    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
