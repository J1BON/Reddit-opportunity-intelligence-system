"""12-hour markdown intelligence report from canonical rows."""

from __future__ import annotations

import json
import time
from sqlite3 import Row


def _row(r: Row, key: str, default: object = "") -> object:
    try:
        return r[key]
    except (KeyError, IndexError):
        return default


def _loads(val: str | None, default: list | dict) -> list | dict:
    if not val:
        return default
    try:
        return json.loads(val)
    except json.JSONDecodeError:
        return default


def build_report(rows: list[Row], window_start: float, window_end: float) -> str:
    total_unique = len(rows)
    dup_collapsed = sum(max(0, int(_row(r, "mentions_count", 0) or 0) - 1) for r in rows)

    def top_by(field: str) -> Row | None:
        if not rows:
            return None
        return max(rows, key=lambda r: float(_row(r, field, 0) or 0))

    def filter_type(ot: str) -> list[Row]:
        return [r for r in rows if str(_row(r, "offer_type", "")) == ot]

    trending = sorted(rows, key=lambda r: float(_row(r, "engagement_score", 0) or 0), reverse=True)[:5]

    bank = sorted(filter_type("bank_bonus"), key=lambda r: float(_row(r, "opportunity_score", 0) or 0), reverse=True)
    sb = sorted(filter_type("sportsbook"), key=lambda r: float(_row(r, "opportunity_score", 0) or 0), reverse=True)
    gems = sorted(rows, key=lambda r: float(_row(r, "hidden_gem_score", 0) or 0), reverse=True)[:8]
    early_movers = sorted(
        rows, key=lambda r: float(_row(r, "first_mover_score", 0) or 0), reverse=True
    )[:12]
    scams = sorted(rows, key=lambda r: float(_row(r, "scam_probability", 0) or 0), reverse=True)[:8]

    best_overall = top_by("opportunity_score")
    best_pay = top_by("reward_amount")  # lex sort on text — crude
    best_trust = top_by("trust_score")
    best_early_mover = top_by("first_mover_score")

    lines = [
        "# USA Reddit Opportunity Intelligence Report",
        "",
        f"Reporting Window: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(window_start))} → "
        f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(window_end))}",
        f"Total Unique Opportunities: {total_unique}",
        f"Approx. Duplicate Posts Collapsed: {dup_collapsed}",
        f"Top Trending Offer (by engagement): {_offer_title(trending[0]) if trending else 'n/a'}",
        f"Best Hidden Gem: {_offer_title(gems[0]) if gems else 'n/a'}",
        f"Highest Payout (text field): {_row(best_pay, 'reward_amount', 'n/a') if best_pay else 'n/a'}",
        f"Most Trusted Offer: {_offer_title(best_trust) if best_trust else 'n/a'}",
        f"Best Bank Bonus: {_offer_title(bank[0]) if bank else 'n/a'}",
        f"Best Sportsbook Bonus: {_offer_title(sb[0]) if sb else 'n/a'}",
        f"Best Early Mover (pre-mainstream): {_offer_title(best_early_mover) if best_early_mover else 'n/a'}",
        "",
        "## Sections snapshot",
        "",
        "1. TOP OPPORTUNITIES — see ranked list below",
        "2. HIGHEST PAYOUTS — reward_amount field",
        "3. TRENDING BONUSES — engagement_score",
        "4. BANK BONUSES — offer_type=bank_bonus",
        "5. SPORTSBOOK PROMOS — offer_type=sportsbook",
        "6. BROKERAGE REWARDS — offer_type=brokerage",
        "7. CRYPTO SIGNUPS — offer_type=crypto_signup",
        "8. HIDDEN GEMS — hidden_gem_score",
        "9. LOW-RISK — low scam_probability + higher trust",
        "10. FASTEST PAYOUTS — heuristic (instant withdrawal keywords in summaries)",
        "11. MOST CONFIRMED — confirmation_count",
        "12. POSSIBLE SCAMS — high scam_probability",
        "13. EXPIRING BONUSES — urgent=1",
        "14. BEST EFFORT-TO-REWARD — opportunity_score",
        "15. LOW-SATURATION — low saturation_score",
        "16. EARLY MOVERS — high first_mover_score (new domains / unknown brands)",
        "",
        "=" * 48,
        "## TOP UNIQUE OPPORTUNITIES",
        "=" * 48,
        "",
    ]

    ranked = sorted(rows, key=lambda r: float(_row(r, "opportunity_score", 0) or 0), reverse=True)[:40]
    for r in ranked:
        lines.extend(_format_opportunity_block(r))

    lines.extend(["", "## Trending (engagement)", ""])
    for r in trending:
        lines.append(f"- {_offer_title(r)} — engagement {_row(r, 'engagement_score', 0)}")

    lines.extend(["", "## Hidden gems", ""])
    for r in gems:
        lines.append(f"- {_offer_title(r)} — gem {_row(r, 'hidden_gem_score', 0)}")

    lines.extend(["", "## Early movers (new apps / fresh domains)", ""])
    for r in early_movers:
        fm = _row(r, "first_mover_score", 0)
        dom = _row(r, "primary_domain", "")
        unk = _row(r, "is_unknown_entity", 0)
        suffix = f" — domain `{dom}`" if dom else ""
        unk_s = "unknown_entity " if int(unk or 0) else ""
        lines.append(
            f"- {unk_s}{_offer_title(r)} — first_mover {fm}{suffix}"
        )

    lines.extend(["", "## Watchlist (possible scams)", ""])
    for r in scams:
        lines.append(
            f"- {_offer_title(r)} — scam_probability {_row(r, 'scam_probability', 0)} — {_row(r, 'trust_reasoning', '')}"
        )

    return "\n".join(lines)


def _offer_title(r: Row | None) -> str:
    if not r:
        return "n/a"
    return str(_row(r, "company_name", _row(r, "canonical_offer_id", "")))


def _format_opportunity_block(r: Row) -> list[str]:
    sources = _loads(str(_row(r, "source_posts_json", "[]")), [])
    links = []
    if isinstance(sources, list):
        for s in sources:
            if isinstance(s, dict) and s.get("permalink"):
                links.append(f"https://reddit.com{s['permalink']}")

    reqs = _loads(str(_row(r, "requirements_json", "[]")), [])
    req_s = ", ".join(reqs) if isinstance(reqs, list) else str(reqs)

    lines = [
        f"## {_row(r, 'company_name', _row(r, 'canonical_offer_id', ''))}",
        "",
        f"Reward: {_row(r, 'reward_amount', '')}",
        f"Requirements: {req_s}",
        f"Deposit Required: {bool(_row(r, 'deposit_required', 0))}",
        f"Eligible States: {_row(r, 'eligible_states_json', '')}",
        f"Trust Score: {_row(r, 'trust_score', '')}",
        f"Opportunity Score: {_row(r, 'opportunity_score', '')}",
        f"Hidden Gem Score: {_row(r, 'hidden_gem_score', '')}",
        f"Saturation Score: {_row(r, 'saturation_score', '')}",
        f"Mentions: {_row(r, 'mentions_count', '')}",
        f"Payout Confirmations: {_row(r, 'confirmation_count', '')}",
        f"Trend Velocity: {_row(r, 'trend_velocity', '')}",
        f"First Mover Score: {_row(r, 'first_mover_score', '')}",
        f"Startup Legitimacy: {_row(r, 'startup_legitimacy_score', '')}",
        f"Predicted Growth: {_row(r, 'predicted_growth_score', '')}",
        f"Saturation Risk: {_row(r, 'saturation_risk', '')}",
        f"Profit Window Hint: {_row(r, 'estimated_profit_window', '')}",
        f"Primary Domain: {_row(r, 'primary_domain', '')}",
        f"Best Signup Strategy: {_row(r, 'best_signup_strategy', '')}",
        f"AI Summary: {_row(r, 'ai_summary', '')}",
        f"Source Links: {' | '.join(links[:12])}",
        "",
    ]
    return lines
