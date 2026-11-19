#!/usr/bin/env python3
"""Audit blameless postmortems and SQLite action-item debt.

Scans 01-postmortem-inc-2026-114.md against blame-language regexes and
loads 02-postmortem-ledger.csv into an in-memory sqlite3 database to
compute overdue P0/P1 counts and emit a release-freeze verdict.

Copyright (c) 2026 Kien Nguyen. Licensed under Apache-2.0.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_POSTMORTEM = BASE_DIR / "01-postmortem-inc-2026-114.md"
DEFAULT_LEDGER = BASE_DIR / "02-postmortem-ledger.csv"
DEFAULT_AS_OF = "2026-11-19"

BLAME_PATTERNS = (
    ("human_error", r"\bhuman\s+error\b"),
    ("careless", r"\bcareless\w*\b"),
    ("negligent", r"\bnegligen\w*\b"),
    ("operator_mistake", r"\boperator\s+mistake\b"),
    ("forgot_to", r"\bforgot\s+to\b"),
    ("failed_to_read", r"\bfailed\s+to\s+read\b"),
    ("should_have_known", r"\bshould\s+have\s+known\b"),
    ("incompetent", r"\bincompeten\w*\b"),
    ("blame_word", r"\bblame(?!less)\w*\b"),
)


def scan_blameless_doc(doc_path: Path) -> list[dict]:
    """Return any blame-oriented regex matches with line numbers."""
    findings: list[dict] = []
    lines = doc_path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines, start=1):
        for label, pattern in BLAME_PATTERNS:
            if re.search(pattern, line, flags=re.IGNORECASE):
                findings.append(
                    {
                        "line": idx,
                        "pattern": label,
                        "excerpt": line.strip()[:56],
                    }
                )
    return findings


def load_ledger_sqlite(csv_path: Path) -> sqlite3.Connection:
    """Load postmortem action items CSV into an in-memory SQLite DB."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE action_items (
            action_id TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL,
            priority TEXT NOT NULL,
            summary TEXT NOT NULL,
            owner_team TEXT NOT NULL,
            due_date TEXT NOT NULL,
            status TEXT NOT NULL,
            blocks_release INTEGER NOT NULL
        )
        """
    )
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            inc_id = row.get("incident_id") or row["inc_id"]
            owner = row.get("owner_team") or row["owner"]
            blocks = 1 if row["blocks_release"].lower() == "true" else 0
            conn.execute(
                """
                INSERT INTO action_items (
                    action_id, incident_id, priority, summary,
                    owner_team, due_date, status, blocks_release
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["action_id"],
                    inc_id,
                    row["priority"],
                    row["summary"],
                    owner,
                    row["due_date"],
                    row["status"],
                    blocks,
                ),
            )
    conn.commit()
    return conn


def query_debt_metrics(conn: sqlite3.Connection, as_of: str) -> dict:
    """Query overdue P0/P1 counts and release verdict from SQLite."""
    cur = conn.cursor()
    total_rows = cur.execute(
        "SELECT COUNT(*) FROM action_items"
    ).fetchone()[0]
    overdue_p0 = cur.execute(
        """
        SELECT COUNT(*) FROM action_items
        WHERE priority = 'P0' AND status != 'closed' AND due_date < ?
        """,
        (as_of,),
    ).fetchone()[0]
    overdue_p1 = cur.execute(
        """
        SELECT COUNT(*) FROM action_items
        WHERE priority = 'P1' AND status != 'closed' AND due_date < ?
        """,
        (as_of,),
    ).fetchone()[0]
    blocking_overdue = cur.execute(
        """
        SELECT action_id, incident_id, priority, owner_team, due_date
        FROM action_items
        WHERE blocks_release = 1
          AND status != 'closed'
          AND due_date < ?
        ORDER BY due_date ASC
        """,
        (as_of,),
    ).fetchall()
    team_debt = cur.execute(
        """
        SELECT owner_team,
               COUNT(*) AS open_cnt,
               SUM(CASE WHEN due_date < ? THEN 1 ELSE 0 END) AS late
        FROM action_items
        WHERE status != 'closed'
        GROUP BY owner_team
        ORDER BY late DESC, open_cnt DESC
        """,
        (as_of,),
    ).fetchall()

    if overdue_p0 > 0 or len(blocking_overdue) > 0:
        verdict = "FREEZE_RELEASES"
    elif overdue_p1 > 0:
        verdict = "WARN_DEBT"
    else:
        verdict = "PASS"

    return {
        "as_of": as_of,
        "total_items": total_rows,
        "overdue_p0": overdue_p0,
        "overdue_p1": overdue_p1,
        "blocking_overdue": [dict(r) for r in blocking_overdue],
        "team_open_debt": [dict(r) for r in team_debt],
        "release_verdict": verdict,
    }


def print_report(
    blame_hits: list[dict],
    debt: dict,
) -> None:
    """Render postmortem hygiene and SQLite debt audit <= 74 chars."""
    print(f"OrderFlow Postmortem Debt Audit (as of {debt['as_of']})")
    print("-" * 72)
    print(f"Blame-Language Findings : {len(blame_hits)}")
    for hit in blame_hits:
        print(
            f"  Line {hit['line']}: [{hit['pattern']}] {hit['excerpt']}"
        )
    print(
        f"Ledger Items: {debt['total_items']} | "
        f"Overdue P0: {debt['overdue_p0']} | "
        f"Overdue P1: {debt['overdue_p1']}"
    )
    print(f"Release Gate Verdict    : {debt['release_verdict']}")
    if debt["blocking_overdue"]:
        print("Overdue Release-Blocking Actions:")
        for item in debt["blocking_overdue"]:
            print(
                f"  - {item['action_id']} ({item['incident_id']} "
                f"{item['priority']}, {item['owner_team']}) "
                f"due {item['due_date']}"
            )
    print("Open Action Debt by Team:")
    for row in debt["team_open_debt"]:
        print(
            f"  - {row['owner_team']:<10}: "
            f"{row['open_cnt']} open ({row['late']} overdue)"
        )
    print("-" * 72)


def main() -> int:
    """Run blameless scan and SQLite debt query CLI."""
    parser = argparse.ArgumentParser(
        description="Audit blameless postmortem and action-item debt."
    )
    parser.add_argument(
        "--postmortem", type=Path, default=DEFAULT_POSTMORTEM
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if blame hits or FREEZE_RELEASES occurs.",
    )
    args = parser.parse_args()

    blame_hits = scan_blameless_doc(args.postmortem)
    conn = load_ledger_sqlite(args.ledger)
    try:
        debt = query_debt_metrics(conn, args.as_of)
    finally:
        conn.close()

    if args.json:
        out = {"blame_findings": blame_hits, "debt_summary": debt}
        print(json.dumps(out, indent=2))
    else:
        print_report(blame_hits, debt)

    if args.strict and (
        blame_hits or debt["release_verdict"] == "FREEZE_RELEASES"
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
