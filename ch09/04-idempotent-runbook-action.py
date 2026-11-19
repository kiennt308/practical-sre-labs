#!/usr/bin/env python3
"""Idempotent, lock-guarded OrderFlow runbook remediation CLI.

Author: Kien Nguyen | License: Apache-2.0
Repo: https://github.com/kiennt308/practical-sre-labs
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ACTION_TO_STATE = {
    "drain": "drained",
    "restore": "active",
}


class ExclusiveLock:
    """Portable exclusive lockfile guard using atomic O_CREAT|O_EXCL."""

    def __init__(self, lock_path: Path, timeout_sec: float = 5.0) -> None:
        self.lock_path = lock_path
        self.timeout_sec = timeout_sec
        self.fd: int | None = None

    def __enter__(self) -> ExclusiveLock:
        deadline = time.monotonic() + self.timeout_sec
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
        while True:
            try:
                self.fd = os.open(str(self.lock_path), flags, 0o600)
                os.write(self.fd, f"pid={os.getpid()}\n".encode("utf-8"))
                return self
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Lock busy: {self.lock_path}")
                time.sleep(0.05)

    def __exit__(self, *args: object) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def read_state(state_path: Path) -> dict[str, dict[str, str]]:
    """Load persisted target state map or initialize empty."""
    if not state_path.exists():
        return {}
    raw = state_path.read_text(encoding="utf-8").strip()
    return json.loads(raw) if raw else {}


def write_state_atomic(
    state_path: Path, state: dict[str, dict[str, str]]
) -> None:
    """Persist state safely via temporary file + atomic replace."""
    tmp_path = state_path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, state_path)


def run_action(
    state_path: Path, target: str, action: str, apply_mode: bool
) -> dict[str, object]:
    """Execute drain/restore idempotently under lockfile protection."""
    lock_path = Path(str(state_path) + ".lock")
    desired = ACTION_TO_STATE[action]
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with ExclusiveLock(lock_path):
        state = read_state(state_path)
        prev = state.get(target, {}).get("status", "active")

        if prev == desired:
            status = "already_in_desired_state"
            changed = False
        elif not apply_mode:
            status = "dry_run_would_change"
            changed = False
        else:
            state[target] = {"status": desired, "updated_utc": now_iso}
            write_state_atomic(state_path, state)
            status = "applied"
            changed = True

    return {
        "timestamp_utc": now_iso,
        "actor": getpass.getuser(),
        "target": target,
        "action": action,
        "mode": "apply" if apply_mode else "dry-run",
        "lock_file": str(lock_path),
        "previous_state": prev,
        "desired_state": desired,
        "status": status,
        "changed": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Idempotent runbook CLI")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("orderflow-drain-state.json"),
    )
    parser.add_argument("--target", required=True)
    parser.add_argument(
        "--action", choices=["drain", "restore"], required=True
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", default=True)
    group.add_argument("--apply", action="store_true", default=False)
    args = parser.parse_args()

    audit = run_action(
        args.state_file, args.target, args.action, apply_mode=args.apply
    )
    print(json.dumps(audit, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
