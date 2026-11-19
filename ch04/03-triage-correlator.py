#!/usr/bin/env python3
"""Correlate OTel trace exemplars and compute ICS TTD/TTM/TTR metrics.

Reads 02-sample-incident-telemetry.json, maps Prometheus burn-rate
exemplars to failing dependency spans, prints the chronological ICS
timeline, and calculates Time to Detect, Mitigate, and Resolve.

Copyright (c) 2026 Kien Nguyen. Licensed under Apache-2.0.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

DEFAULT_INPUT = Path(__file__).with_name(
    "02-sample-incident-telemetry.json"
)


def parse_utc(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp ending in Z."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def minutes_between(start_ts: str, end_ts: str) -> float:
    """Return elapsed minutes between two ISO-8601 timestamps."""
    delta = parse_utc(end_ts) - parse_utc(start_ts)
    return round(delta.total_seconds() / 60.0, 2)


def correlate_incident(payload: dict) -> dict:
    """Correlate exemplars to bottlenecks and extract TTD/TTM/TTR."""
    timeline = sorted(
        payload["timeline_events"],
        key=lambda ev: parse_utc(ev["timestamp_utc"]),
    )
    phase_times = {
        ev["phase"]: ev["timestamp_utc"] for ev in timeline
    }

    fault_ts = phase_times["fault_start"]
    detect_ts = phase_times["detected"]
    mitigate_ts = phase_times["mitigated"]
    resolve_ts = phase_times["resolved"]

    dep_counts: Counter[str] = Counter()
    correlated_traces = []
    for ex in payload["otel_exemplars"]:
        span = ex["failing_span"]
        dep_counts[span["dependency"]] += 1
        correlated_traces.append(
            {
                "exemplar_id": ex["exemplar_id"],
                "trace_id": ex["trace_id"],
                "service": span["service"],
                "dependency": span["dependency"],
                "operation": span["operation"],
                "duration_ms": span["duration_ms"],
                "pool_usage": (
                    f"{span['db_pool_active']}/{span['db_pool_max']}"
                ),
            }
        )

    primary_bottleneck, hits = dep_counts.most_common(1)[0]
    return {
        "incident_id": payload["incident_id"],
        "severity": payload["severity"],
        "region": payload["region"],
        "alertname": payload["alert"]["alertname"],
        "primary_bottleneck": primary_bottleneck,
        "bottleneck_exemplar_hits": hits,
        "ics_roles": payload["ics_assignments"],
        "metrics_minutes": {
            "ttd_from_fault": minutes_between(fault_ts, detect_ts),
            "ttm_from_detect": minutes_between(detect_ts, mitigate_ts),
            "ttm_from_fault": minutes_between(fault_ts, mitigate_ts),
            "ttr_from_detect": minutes_between(detect_ts, resolve_ts),
            "ttr_from_fault": minutes_between(fault_ts, resolve_ts),
        },
        "correlated_exemplars": correlated_traces,
        "timeline": timeline,
    }


def print_brief(report: dict) -> None:
    """Render an operator-friendly triage brief <= 74 chars wide."""
    m = report["metrics_minutes"]
    print(
        f"ICS Triage Brief: {report['incident_id']} "
        f"[{report['severity']} | {report['region']}]"
    )
    print("-" * 72)
    print(f"Trigger Alert : {report['alertname']}")
    print(
        f"Bottleneck    : {report['primary_bottleneck']} "
        f"({report['bottleneck_exemplar_hits']} correlated exemplars)"
    )
    roles = report["ics_roles"]
    print(
        f"ICS Roles     : IC={roles['IC']} OL={roles['OL']} "
        f"CL={roles['CL']} Scribe={roles['Scribe']}"
    )
    print(
        f"Timings (min) : TTD={m['ttd_from_fault']:.1f}m | "
        f"TTM={m['ttm_from_detect']:.1f}m (post-alert) | "
        f"TTR={m['ttr_from_detect']:.1f}m"
    )
    print("-" * 72)
    print("Correlated OTel v0.165 Trace Exemplars:")
    for tr in report["correlated_exemplars"]:
        print(
            f"  {tr['exemplar_id']} trace={tr['trace_id'][:16]}... "
            f"{tr['service']} -> {tr['dependency']}"
        )
        print(
            f"    op={tr['operation']} dur={tr['duration_ms']}ms "
            f"pool={tr['pool_usage']}"
        )
    print("-" * 72)
    print("Chronological ICS Timeline (UTC):")
    for ev in report["timeline"]:
        ts = ev["timestamp_utc"][11:19]
        print(f"  {ts}Z [{ev['phase']:<17}] {ev['detail']}")
    print("-" * 72)


def main() -> int:
    """Load telemetry fixture, correlate traces, and print report."""
    parser = argparse.ArgumentParser(
        description="Correlate OTel exemplars and compute TTD/TTM/TTR."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to incident telemetry JSON fixture.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit triage report as JSON.",
    )
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = correlate_incident(payload)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_brief(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
