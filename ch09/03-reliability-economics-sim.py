#!/usr/bin/env python3
"""Audit SRE toil cap (<50%) and SLO reliability economics via SQLite.

Author: Kien Nguyen | License: Apache-2.0
Repo: https://github.com/kiennt308/practical-sre-labs
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TOIL_CSV = BASE_DIR / "01-toil-ledger.csv"
FOCUS_CSV = BASE_DIR / "02-focus12-unit-cost-bridge.csv"
DOWNTIME_LOSS_PER_HOUR = 42000.0


def load_tables(
    conn: sqlite3.Connection, toil_path: Path, focus_path: Path
) -> None:
    """Create SQLite tables and import toil and FOCUS 1.2 CSVs."""
    conn.execute(
        """
        CREATE TABLE toil_ledger (
          task_id TEXT PRIMARY KEY,
          category TEXT NOT NULL,
          is_toil INTEGER NOT NULL,
          weekly_hours REAL NOT NULL,
          automation_build_hours REAL NOT NULL,
          blast_risk TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """
        CREATE TABLE focus_bridge (
          slo_tier TEXT PRIMARY KEY,
          arch_profile TEXT NOT NULL,
          orders_k REAL NOT NULL,
          unit_1k_usd REAL NOT NULL,
          infra_usd REAL NOT NULL,
          downtime_min REAL NOT NULL
        );
        """
    )
    with toil_path.open("r", encoding="utf-8", newline="") as handle:
        rows = [
            (
                r["task_id"],
                r["category"],
                1 if r["is_toil"].strip().lower() == "true" else 0,
                float(r["weekly_hours"]),
                float(r["automation_build_hours"]),
                r["blast_risk"],
            )
            for r in csv.DictReader(handle)
        ]
    conn.executemany(
        "INSERT INTO toil_ledger VALUES (?, ?, ?, ?, ?, ?)", rows
    )

    with focus_path.open("r", encoding="utf-8", newline="") as handle:
        frows = [
            (
                r["slo_tier"],
                r["arch_profile"],
                float(r["orders_k"]),
                float(r["unit_1k_usd"]),
                float(r["infra_usd"]),
                float(r["downtime_min"]),
            )
            for r in csv.DictReader(handle)
        ]
    conn.executemany(
        "INSERT INTO focus_bridge VALUES (?, ?, ?, ?, ?, ?)", frows
    )
    conn.commit()


def audit_toil(conn: sqlite3.Connection) -> None:
    """Audit baseline toil against Google <50% cap and rank payback."""
    row = conn.execute(
        """
        SELECT
          SUM(weekly_hours) AS total_h,
          SUM(CASE WHEN is_toil=1 THEN weekly_hours ELSE 0 END) AS toil_h
        FROM toil_ledger;
        """
    ).fetchone()
    total_h, toil_h = float(row[0]), float(row[1])
    base_pct = 100.0 * toil_h / total_h
    cap_status = "BREACH (>50%)" if base_pct > 50.0 else "OK (<=50%)"

    print("=== Toil Ledger Audit (Google SRE <50% Cap) ===")
    print(f"Total team hours/wk : {total_h:.1f}h")
    print(f"Baseline toil/wk    : {toil_h:.1f}h ({base_pct:.1f}%)")
    print(f"Cap status          : {cap_status}")

    candidates = conn.execute(
        """
        SELECT
          task_id,
          category,
          weekly_hours,
          automation_build_hours,
          ROUND(automation_build_hours / weekly_hours, 2) AS payback_wks,
          blast_risk
        FROM toil_ledger
        WHERE is_toil = 1
        ORDER BY payback_wks ASC;
        """
    ).fetchall()

    print("\nTop Automation Candidates (by Payback Weeks):")
    hdr = (
        f"{'Task':<8} {'Category':<18} {'Hrs/W':>5} "
        f"{'Bld':>5} {'Pay':>6}"
    )
    print(hdr)
    for c in candidates:
        row_txt = (
            f"{c[0]:<8} {c[1]:<18} {c[2]:>5.1f} "
            f"{c[3]:>5.1f} {c[4]:>5.2f}w"
        )
        print(row_txt)

    saved_h = 0.0
    build_h = 0.0
    automated: list[str] = []
    for c in candidates:
        automated.append(c[0])
        saved_h += float(c[2])
        build_h += float(c[3])
        if ((toil_h - saved_h) / total_h) * 100.0 < 35.0:
            break

    post_h = toil_h - saved_h
    post_pct = 100.0 * post_h / total_h
    print(f"\nAutomate top {len(automated)}: {', '.join(automated)}")
    print(f"Total build effort  : {build_h:.1f}h (saved {saved_h:.1f}h)")
    print(f"Post-auto toil/wk   : {post_h:.1f}h ({post_pct:.1f}% < 35%)")


def evaluate_economics(conn: sqlite3.Connection) -> None:
    """Compare infra spend + $42k/h downtime risk across SLO tiers."""
    rows = conn.execute(
        """
        SELECT
          slo_tier,
          unit_1k_usd,
          infra_usd,
          downtime_min,
          ROUND((downtime_min / 60.0) * ?, 2) AS risk_usd,
          ROUND(infra_usd + (downtime_min / 60.0) * ?, 2) AS total_usd
        FROM focus_bridge
        ORDER BY total_usd ASC;
        """,
        (DOWNTIME_LOSS_PER_HOUR, DOWNTIME_LOSS_PER_HOUR),
    ).fetchall()

    print("\n=== Reliability Economics (FOCUS 1.2 vs $42,000/h Loss) ===")
    print("Vol. 04 Anchor: $1.05 (eu-west-1) / $1.15 (us-east-1) per 1k")
    print(
        f"{'SLO':<8} {'$/1k':>6} {'Infra$':>9} "
        f"{'DownMin':>8} {'Risk$':>9} {'Total$':>10}"
    )
    by_tier = sorted(rows, key=lambda r: float(r[0].rstrip("%")))
    for r in by_tier:
        print(
            f"{r[0]:<8} {r[1]:>6.2f} {r[2]:>9.0f} "
            f"{r[3]:>8.2f} {r[4]:>9.0f} {r[5]:>10.0f}"
        )
    best = rows[0]
    five_nines = [r for r in rows if r[0] == "99.995%"][0]
    delta = float(five_nines[5]) - float(best[5])
    print(
        f"\nOptimal SLO tier    : {best[0]} at ${best[5]:,.0f}/mo total "
        f"(saves ${delta:,.0f}/mo vs premature 99.995%)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Economics simulator")
    parser.add_argument("--toil-csv", type=Path, default=TOIL_CSV)
    parser.add_argument("--focus-csv", type=Path, default=FOCUS_CSV)
    args = parser.parse_args()

    conn = sqlite3.connect(":memory:")
    try:
        load_tables(conn, args.toil_csv, args.focus_csv)
        audit_toil(conn)
        evaluate_economics(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
