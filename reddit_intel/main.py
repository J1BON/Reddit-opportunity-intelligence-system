"""CLI: polling daemon (default backfill interval), one-shot fetch, 12h report."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from reddit_intel.config import (
    BACKFILL_INTERVAL_SECONDS,
    REPORT_INTERVAL_SECONDS,
)
from reddit_intel.database import Database
from reddit_intel.engine import run_fetch_cycle, run_report
from reddit_intel.reddit_client import make_reddit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="USA Reddit Opportunity Intelligence collector")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single fetch cycle over priority subs then exit",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Quick connectivity test: 3 subs × 5 posts, no discovery (sets SMOKE_FETCH=1)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Loop forever: fetch every BACKFILL_INTERVAL_SECONDS (default 300)",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Emit a 12-hour markdown report to stdout and store in DB",
    )
    parser.add_argument(
        "--report-window-hours",
        type=float,
        default=12.0,
        help="Reporting window in hours (default 12)",
    )
    args = parser.parse_args(argv)

    if args.smoke and args.daemon:
        print("--smoke cannot be combined with --daemon", file=sys.stderr)
        return 2
    if args.smoke:
        os.environ["SMOKE_FETCH"] = "1"

    db = Database()

    if args.report:
        md = run_report(db, window_seconds=float(args.report_window_hours) * 3600.0)
        print(md)
        out_dir = Path(__file__).resolve().parents[1] / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = out_dir / f"intel_{int(time.time())}.md"
        fname.write_text(md, encoding="utf-8")
        print(f"\n[saved] {fname}", file=sys.stderr)
        if not args.once and not args.daemon:
            return 0

    try:
        reddit = make_reddit()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.once or args.smoke or not args.daemon:
        n = run_fetch_cycle(reddit, db)
        print(f"[cycle] ingested/processed {n} matching posts", file=sys.stderr)
        return 0

    next_report = time.time() + REPORT_INTERVAL_SECONDS
    print(
        f"[daemon] fetch every {BACKFILL_INTERVAL_SECONDS}s; "
        f"report every {REPORT_INTERVAL_SECONDS}s",
        file=sys.stderr,
    )
    while True:
        try:
            n = run_fetch_cycle(reddit, db)
            print(f"[cycle] processed {n} posts @ {time.strftime('%H:%M:%S')}", file=sys.stderr)
        except Exception as ex:
            print(f"[cycle error] {ex}", file=sys.stderr)

        now = time.time()
        if now >= next_report:
            md = run_report(db, window_seconds=float(REPORT_INTERVAL_SECONDS))
            out_dir = Path(__file__).resolve().parents[1] / "reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"intel_{int(now)}.md").write_text(md, encoding="utf-8")
            print("[report] wrote 12h intelligence markdown", file=sys.stderr)
            next_report = now + REPORT_INTERVAL_SECONDS

        time.sleep(BACKFILL_INTERVAL_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
