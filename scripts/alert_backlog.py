"""Fire Discord alerts for canonical offers already in the DB.

Use case: you ran the bot locally before Discord was wired up, so the alert
thresholds matched but no Discord messages went out. The cooldown rows in
``alerts_log`` now block normal re-alerts. Run this script once to flush the
backlog into your Discord channel.

After this initial flush, the cron's normal alert flow handles new
opportunities automatically.

Run via the ``Alert backlog`` GitHub Action, or locally:

    py -3 -m scripts.alert_backlog                    # default: last 14 days, top 25
    py -3 -m scripts.alert_backlog --hours 48 --max 10
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from reddit_intel.alerts import (
    format_alert,
    format_early_gem_alert,
    notify_alert_destinations,
    send_console_alert,
)
from reddit_intel.config import (
    ALERT_MIN_OPPORTUNITY_SCORE,
    ALERT_MIN_PAYOUT_USD,
)
from reddit_intel.database import Database


def _max_reward_usd(reward_amount: str | None) -> float:
    try:
        return float(str(reward_amount or "").replace("$", "").strip() or 0)
    except ValueError:
        return 0.0


def _meets_standard_threshold(row: dict[str, Any]) -> bool:
    reward = _max_reward_usd(row.get("reward_amount"))
    opp = float(row.get("opportunity_score") or 0)
    gem = float(row.get("hidden_gem_score") or 0)
    urgent = bool(row.get("urgent"))
    trust = float(row.get("trust_score") or 0)
    ot = str(row.get("offer_type") or "")
    if reward >= ALERT_MIN_PAYOUT_USD:
        return True
    if opp >= ALERT_MIN_OPPORTUNITY_SCORE:
        return True
    if gem >= 70:
        return True
    if urgent and trust >= 40:
        return True
    if ot in ("bank_bonus", "brokerage", "sportsbook") and reward >= 15:
        return True
    if ot == "crypto_signup" and reward >= 25:
        return True
    return False


def _build_payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        sources = json.loads(row.get("source_posts_json") or "[]")
    except json.JSONDecodeError:
        sources = []
    try:
        refurls = json.loads(row.get("referral_links_json") or "[]")
    except json.JSONDecodeError:
        refurls = []
    try:
        reqs = json.loads(row.get("requirements_json") or "[]")
    except json.JSONDecodeError:
        reqs = []

    links: list[str] = []
    if isinstance(sources, list):
        for s in sources:
            if isinstance(s, dict) and s.get("permalink"):
                links.append(f"https://reddit.com{s['permalink']}")
    if isinstance(refurls, list):
        links.extend(str(u) for u in refurls[:5])

    return {
        "company_name": row.get("company_name"),
        "reward_amount": row.get("reward_amount"),
        "requirements": ", ".join(reqs) if isinstance(reqs, list) else "",
        "deposit_needed": bool(row.get("deposit_required")),
        "states": "USA scope unclear — verify terms",
        "trust_score": round(float(row.get("trust_score") or 0), 1),
        "mentions": row.get("mentions_count"),
        "trend_velocity": row.get("trend_velocity"),
        "hidden_gem_score": round(float(row.get("hidden_gem_score") or 0), 1),
        "ai_summary": row.get("ai_summary"),
        "links": " | ".join(links[:12]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fire Discord alerts for backlog canonical offers (ignores per-offer cooldown)."
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=14 * 24,
        help="Look at canonical offers updated within this many hours (default: 336 = 14 days).",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=25,
        help="Maximum alerts to fire in one run (default: 25). Prevents flooding Discord.",
    )
    parser.add_argument(
        "--rate-limit-seconds",
        type=float,
        default=1.2,
        help="Sleep between alerts to stay under Discord's 5-msg/5s limit (default: 1.2s).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what WOULD be sent without actually firing Discord/webhook.",
    )
    args = parser.parse_args(argv)

    db = Database()
    since = time.time() - (args.hours * 3600.0)
    rows = [dict(r) for r in db.fetch_recent_canonical(since)]

    eligible = [r for r in rows if _meets_standard_threshold(r)]
    eligible.sort(
        key=lambda r: (
            float(r.get("opportunity_score") or 0),
            _max_reward_usd(r.get("reward_amount")),
        ),
        reverse=True,
    )

    print(
        f"[backlog] candidates_in_window={len(rows)} eligible={len(eligible)} "
        f"will_fire={min(len(eligible), args.max)} dry_run={args.dry_run}",
        flush=True,
    )

    fired = 0
    for row in eligible[: args.max]:
        payload = _build_payload(row)
        text = format_alert(payload)
        send_console_alert(text)
        if not args.dry_run:
            notify_alert_destinations(text)
            db.log_alert(str(row.get("canonical_offer_id")), payload, alert_kind="backlog")
            time.sleep(args.rate_limit_seconds)
        fired += 1

    print(f"[backlog] fired={fired}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
