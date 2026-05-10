"""Export canonical_offers from SQLite to docs/offers.json for the web dashboard.

The cron workflow runs this after each fetch cycle and commits the result.
GitHub Pages then serves docs/index.html which fetches offers.json client-side.

Layout (lean — keeps the file small even at thousands of offers):

    {
      "generated_at": "2026-05-10T22:30:00Z",
      "total_offers": 23,
      "offer_types":   {"bank_bonus": 4, "referral": 18, ...},
      "offers": [ {...}, ... ]   # newest first by latest_seen
    }

Each offer carries only the fields the UI actually renders (≈ 25 keys),
not the entire canonical_offers row.

Run via the cron workflow, or locally:

    py -3 -m scripts.export_dashboard
    py -3 -m scripts.export_dashboard --out custom/path.json --limit 500
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from reddit_intel.database import Database
from reddit_intel.dedupe import brand_display_name, clean_post_title, pick_brand


def _safe_list(blob: Any) -> list[Any]:
    if not blob:
        return []
    try:
        v = json.loads(blob) if isinstance(blob, str) else blob
        return v if isinstance(v, list) else []
    except json.JSONDecodeError:
        return []


def _reward_usd(reward_amount: str | None) -> float:
    try:
        return float(str(reward_amount or "").replace("$", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _iso_z(ts: float | None) -> str:
    if not ts:
        return ""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))
    except (TypeError, ValueError):
        return ""


def _row_to_offer(row: dict[str, Any]) -> dict[str, Any]:
    sources = _safe_list(row.get("source_posts_json"))
    referrals_raw = _safe_list(row.get("referral_links_json"))
    subs = _safe_list(row.get("subreddits_json"))
    requirements = _safe_list(row.get("requirements_json"))
    eligible_states = _safe_list(row.get("eligible_states_json"))
    excluded_states = _safe_list(row.get("excluded_states_json"))

    reddit_links: list[str] = []
    for s in sources:
        if isinstance(s, dict) and s.get("permalink"):
            link = f"https://reddit.com{s['permalink']}"
            if link not in reddit_links:
                reddit_links.append(link)

    referral_links: list[str] = []
    for u in referrals_raw:
        su = str(u or "").strip()
        if su and "reddit.com" not in su and su not in referral_links:
            referral_links.append(su)

    reward_str = str(row.get("reward_amount") or "").strip()
    reward_usd = _reward_usd(reward_str)

    # Recompute brand + cleaned title using the current rules, even for
    # legacy rows where ``company_name`` and ``ai_summary`` were filled in
    # by an older buggy version. The first source post's title is the
    # authoritative human label for the offer.
    first_source = sources[0] if sources and isinstance(sources[0], dict) else {}
    source_title = (
        row.get("post_title")
        or row.get("post_title_clean")
        or first_source.get("title")
        or ""
    )
    primary_domain = (row.get("primary_domain") or "").strip()
    domains_for_brand = [primary_domain] if primary_domain else []
    brand_slug = pick_brand(source_title, row.get("ai_summary") or "", domains_for_brand)
    brand_display = brand_display_name(brand_slug)
    title_clean = clean_post_title(source_title, max_chars=140)

    # If we have a recognised brand, use it as the headline; otherwise fall
    # back to the cleaned post title (so the card still shows something
    # meaningful for off-topic / unknown-brand rows).
    if brand_display:
        company_out = brand_display
    elif title_clean:
        company_out = title_clean[:60]
    else:
        company_out = row.get("company_name") or ""

    return {
        "id": row.get("canonical_offer_id"),
        "company": company_out,
        "brand_slug": brand_slug,
        "post_title": title_clean,
        "type": row.get("offer_type") or "",
        "reward": reward_str,
        "reward_usd": reward_usd,
        "currency": row.get("currency") or "USD",
        "trust": round(float(row.get("trust_score") or 0), 1),
        "scam": round(float(row.get("scam_probability") or 0), 1),
        "gem": round(float(row.get("hidden_gem_score") or 0), 1),
        "opportunity": round(float(row.get("opportunity_score") or 0), 1),
        "first_mover": round(float(row.get("first_mover_score") or 0), 1),
        "engagement": round(float(row.get("engagement_score") or 0), 1),
        "saturation": round(float(row.get("saturation_score") or 0), 1),
        "risk": round(float(row.get("risk_score") or 0), 1),
        "mentions": int(row.get("mentions_count") or 0),
        "confirmations": int(row.get("confirmation_count") or 0),
        "trend": row.get("trend_velocity") or "",
        "first_seen": _iso_z(row.get("first_seen")),
        "latest_seen": _iso_z(row.get("latest_seen")),
        "first_seen_ts": float(row.get("first_seen") or 0),
        "latest_seen_ts": float(row.get("latest_seen") or 0),
        "subreddits": [str(x) for x in subs if x],
        "reddit_links": reddit_links[:8],
        "referral_links": referral_links[:8],
        "primary_domain": row.get("primary_domain") or "",
        "ai_summary": row.get("ai_summary") or "",
        "strategy": row.get("best_signup_strategy") or "",
        "trust_reasoning": row.get("trust_reasoning") or "",
        "requirements": [str(x) for x in requirements if x],
        "deposit_required": bool(row.get("deposit_required")),
        "direct_deposit_required": bool(row.get("direct_deposit_required")),
        "ssn_required": bool(row.get("ssn_required")),
        "urgent": bool(row.get("urgent")),
        "launch_status": row.get("launch_status") or "",
        "profit_window": row.get("estimated_profit_window") or "",
        "eligible_states": [str(x) for x in eligible_states if x],
        "excluded_states": [str(x) for x in excluded_states if x],
    }


def export(out_path: Path, limit: int | None = None) -> dict[str, Any]:
    db = Database()
    with db.connect() as conn:
        cur = conn.execute(
            """
            SELECT * FROM canonical_offers
            ORDER BY latest_seen DESC
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    if limit is not None and limit > 0:
        rows = rows[:limit]

    offers = [_row_to_offer(r) for r in rows]

    type_counts: dict[str, int] = {}
    for o in offers:
        t = o.get("type") or "unknown"
        type_counts[t] = type_counts.get(t, 0) + 1

    sub_counts: dict[str, int] = {}
    for o in offers:
        for s in o.get("subreddits") or []:
            sl = str(s).lower()
            if sl:
                sub_counts[sl] = sub_counts.get(sl, 0) + 1

    try:
        discovered = db.list_discovered_subreddits(limit=40)
    except Exception:
        discovered = []

    payload = {
        "generated_at": _iso_z(time.time()),
        "generated_at_ts": time.time(),
        "total_offers": len(offers),
        "offer_types": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
        "top_subreddits": dict(
            sorted(sub_counts.items(), key=lambda kv: -kv[1])[:20]
        ),
        "discovered_subreddits": [
            {
                "subreddit": d.get("subreddit"),
                "hit_count": int(d.get("hit_count") or 0),
                "first_seen": _iso_z(d.get("first_seen")),
                "last_seen": _iso_z(d.get("last_seen")),
            }
            for d in discovered
        ],
        "offers": offers,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    return {
        "path": str(out_path),
        "total_offers": payload["total_offers"],
        "bytes": out_path.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export canonical_offers to docs/offers.json for the static dashboard."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "offers.json",
        help="Output JSON path (default: docs/offers.json).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=2000,
        help="Cap on offers in the output (newest first). 0/negative = no limit.",
    )
    args = parser.parse_args(argv)

    limit = args.limit if args.limit and args.limit > 0 else None
    summary = export(args.out, limit=limit)
    print(
        f"[export-dashboard] wrote {summary['path']} "
        f"offers={summary['total_offers']} bytes={summary['bytes']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
