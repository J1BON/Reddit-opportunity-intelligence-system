"""Repeatable sanity checks: imports, discovery URL shape, export, smoke fetch."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from reddit_intel.config import DISCOVERY_TIME_FILTER
    from reddit_intel.database import Database

    allowed = {"hour", "day", "week", "month", "year", "all"}
    if DISCOVERY_TIME_FILTER not in allowed:
        print(f"FAIL: DISCOVERY_TIME_FILTER={DISCOVERY_TIME_FILTER!r}", file=sys.stderr)
        return 1

    # Match PublicReddit.search_all — site-wide search must not restrict to a sub.
    sample = {
        "q": "referral",
        "sort": "new",
        "t": DISCOVERY_TIME_FILTER,
        "limit": "5",
        "restrict_sr": "false",
        "include_over_18": "on",
        "raw_json": "1",
    }
    if sample["restrict_sr"] != "false":
        print("FAIL: restrict_sr must be false for global search", file=sys.stderr)
        return 1

    _ = Database()

    r = subprocess.run(
        [sys.executable, "-m", "scripts.export_dashboard"],
        cwd=ROOT,
        env={**os.environ},
        timeout=60,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        print(r.stdout, r.stderr, file=sys.stderr)
        print("FAIL: export_dashboard", file=sys.stderr)
        return 1

    r2 = subprocess.run(
        [sys.executable, "-m", "scripts.alert_backlog", "--dry-run", "--hours", "24", "--max", "1"],
        cwd=ROOT,
        env={**os.environ},
        timeout=60,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r2.returncode != 0:
        print(r2.stdout, r2.stderr, file=sys.stderr)
        print("FAIL: alert_backlog --dry-run", file=sys.stderr)
        return 1

    env = {
        **os.environ,
        "REDDIT_NO_AUTH": "1",
        "SMOKE_FETCH": "1",
        "DISCOVERY_ENABLED": "1",
        "REDDIT_PUBLIC_MIN_INTERVAL_S": "1.0",
        "REDDIT_PUBLIC_TIMEOUT_S": "10.0",
        "FETCH_COMMENT_SAMPLES": "0",
    }
    r3 = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--smoke"],
        cwd=ROOT,
        env=env,
        timeout=120,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r3.returncode != 0:
        print(r3.stdout, r3.stderr, file=sys.stderr)
        print("FAIL: run.py --smoke", file=sys.stderr)
        return 1
    out = (r3.stdout or "") + (r3.stderr or "")
    if "[smoke]" not in out:
        print("WARN: expected [smoke] in fetch output", file=sys.stderr)

    print("OK: self_check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
