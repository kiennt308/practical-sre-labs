#!/usr/bin/env python3
"""Audit 14-day OrderFlow on-call shift load and noisy alert rules.

Evaluates a deterministic 14-day multi-region shift log across
us-east-1 and eu-west-1, flags shifts with > 2 off-hours pages,
computes interrupt load %, and ranks noisy rules for tuning.

Copyright (c) 2026 Kien Nguyen. Licensed under Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass

SHIFT_MINUTES = 12 * 60
OFF_HOURS_PAGE_CAP = 2
MINUTES_PER_INTERRUPT = 35


@dataclass(frozen=True)
class PageEvent:
    """Single alert delivery recorded during a 12-hour on-call shift."""

    rule_name: str
    service: str
    off_hours: bool
    actionable: bool


@dataclass(frozen=True)
class ShiftLog:
    """Deterministic 12-hour regional shift record."""

    day: int
    region: str
    responder: str
    events: tuple[PageEvent, ...]


def sample_shifts() -> list[ShiftLog]:
    """Return a realistic 14-day multi-region shift dataset."""
    ev_fast = PageEvent(
        "OrderflowCheckoutFastBurnPage", "order-gateway", True, True
    )
    ev_cpu = PageEvent(
        "LegacyHighPodCPUWarning", "order-service", True, False
    )
    ev_retry = PageEvent(
        "PaymentWorkerRetryBurst", "payment-worker", True, False
    )
    ev_cache = PageEvent(
        "ValkeyEvictionNotice", "orderflow-valkey-cache", False, False
    )
    ev_db = PageEvent(
        "AuroraPoolSaturationPage",
        "orderflow-global-aurora",
        True,
        True,
    )

    records = [
        (1, "us-east-1", "sre-a", (ev_cpu,)),
        (2, "eu-west-1", "sre-b", ()),
        (3, "us-east-1", "sre-a", (ev_cpu, ev_retry, ev_fast)),
        (4, "eu-west-1", "sre-b", (ev_cache,)),
        (5, "us-east-1", "sre-c", (ev_cpu, ev_cpu, ev_retry, ev_db)),
        (6, "eu-west-1", "sre-d", (ev_retry,)),
        (7, "us-east-1", "sre-c", ()),
        (8, "eu-west-1", "sre-d", (ev_cpu, ev_retry)),
        (9, "us-east-1", "sre-e", (ev_fast,)),
        (10, "eu-west-1", "sre-f", (ev_cpu, ev_cpu, ev_retry)),
        (11, "us-east-1", "sre-e", (ev_cache, ev_retry)),
        (12, "eu-west-1", "sre-f", ()),
        (13, "us-east-1", "sre-a", (ev_db, ev_cpu)),
        (14, "eu-west-1", "sre-b", (ev_cpu,)),
    ]
    return [ShiftLog(d, r, resp, evs) for d, r, resp, evs in records]


def analyze_shifts(shifts: list[ShiftLog]) -> dict:
    """Compute shift violations, interrupt load %, and noisy rules."""
    flagged_shifts = []
    rule_counts: Counter[str] = Counter()
    noisy_counts: Counter[str] = Counter()
    total_events = 0
    total_off_hours = 0

    for sh in shifts:
        off_hours_pages = sum(1 for e in sh.events if e.off_hours)
        shift_pages = len(sh.events)
        raw_pct = (
            shift_pages * MINUTES_PER_INTERRUPT / SHIFT_MINUTES
        ) * 100
        interrupt_pct = round(min(100.0, raw_pct), 2)
        total_events += shift_pages
        total_off_hours += off_hours_pages

        for ev in sh.events:
            rule_counts[ev.rule_name] += 1
            if not ev.actionable:
                noisy_counts[ev.rule_name] += 1

        if off_hours_pages > OFF_HOURS_PAGE_CAP:
            flagged_shifts.append(
                {
                    "day": sh.day,
                    "region": sh.region,
                    "responder": sh.responder,
                    "off_hours_pages": off_hours_pages,
                    "interrupt_load_pct": interrupt_pct,
                }
            )

    total_shift_min = len(shifts) * SHIFT_MINUTES
    fleet_interrupt_pct = round(
        (total_events * MINUTES_PER_INTERRUPT / total_shift_min) * 100,
        2,
    )
    noisy_ranking = [
        {"rule": name, "non_actionable_pages": count}
        for name, count in noisy_counts.most_common()
    ]
    return {
        "shifts_audited": len(shifts),
        "off_hours_cap_per_shift": OFF_HOURS_PAGE_CAP,
        "total_pages": total_events,
        "total_off_hours_pages": total_off_hours,
        "fleet_interrupt_load_pct": fleet_interrupt_pct,
        "flagged_shifts": flagged_shifts,
        "top_noisy_rules": noisy_ranking,
    }


def print_report(summary: dict) -> None:
    """Render a compact audit summary within 74-char line limits."""
    print("OrderFlow 14-Day On-Call Load Audit (us-east-1 / eu-west-1)")
    print("-" * 72)
    print(
        f"Shifts: {summary['shifts_audited']} | "
        f"Pages: {summary['total_pages']} "
        f"(Off-hours: {summary['total_off_hours_pages']}) | "
        f"Interrupt: {summary['fleet_interrupt_load_pct']:.2f}%"
    )
    print(
        f"Flagged Shifts (> {summary['off_hours_cap_per_shift']} "
        f"off-hours pages): {len(summary['flagged_shifts'])}"
    )
    for item in summary["flagged_shifts"]:
        print(
            f"  Day {item['day']:02d} [{item['region']}] "
            f"{item['responder']}: {item['off_hours_pages']} off-hours "
            f"(Load {item['interrupt_load_pct']:.1f}%)"
        )
    print("Top Noisy Rules Requiring Tuning or Inhibition:")
    for rule in summary["top_noisy_rules"]:
        print(
            f"  - {rule['rule']}: "
            f"{rule['non_actionable_pages']} non-actionable pages"
        )
    print("-" * 72)


def main() -> int:
    """Run the 14-day OrderFlow on-call load audit."""
    parser = argparse.ArgumentParser(
        description="Audit 14-day OrderFlow on-call load."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit audit summary as JSON.",
    )
    args = parser.parse_args()

    summary = analyze_shifts(sample_shifts())
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_report(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
