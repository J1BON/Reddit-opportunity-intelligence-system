"""Heuristic scores 0–100: trust, scam, hidden gem, opportunity, saturation."""

from __future__ import annotations

import math

from reddit_intel.detectors import (
    classify_offer_type,
    keyword_hit_count,
    payout_confirmation_hits,
    scam_signals,
    subreddit_priority,
    urgency_hits,
    usa_boost_score,
)


def difficulty_score(text: str, req_dd: bool, req_ssn: bool) -> float:
    base = 30.0
    if req_dd:
        base += 25
    if req_ssn:
        base += 15
    if "verify" in text.lower() or "kyc" in text.lower():
        base += 10
    return min(100.0, base)


def scam_probability(text: str, author_karma_unknown: bool = True) -> float:
    sigs = scam_signals(text)
    p = min(100.0, len(sigs) * 18.0)
    if author_karma_unknown:
        p += 5
    return min(100.0, p)


def trust_score(
    text: str,
    confirmation_count: int,
    mentions_count: int,
    subreddit: str,
) -> float:
    t = 45.0
    t += min(30.0, confirmation_count * 6.0)
    t += usa_boost_score(text)
    pri = subreddit_priority(subreddit)
    t += pri * 5
    if mentions_count > 30:
        t -= min(15.0, (mentions_count - 30) * 0.3)
    return max(0.0, min(100.0, t))


def saturation_score(mentions_count: int, subreddit_count: int, score_sum: float) -> float:
    # More mentions across subs + vote mass ≈ more saturated
    m = mentions_count * 4 + subreddit_count * 10 + math.log1p(max(0.0, score_sum))
    return max(0.0, min(100.0, m))


def hidden_gem_score(
    post_score: int,
    num_comments: int,
    saturation: float,
    max_reward_usd: float,
    trust: float,
    first_mover: float = 0.0,
) -> float:
    low_vis = 100.0 / (1.0 + math.log1p(max(1, post_score + num_comments)))
    payout_fit = min(40.0, max_reward_usd / 3.0) if max_reward_usd else 5.0
    trust_fit = trust * 0.35
    sat_penalty = saturation * 0.35
    early_fit = min(18.0, first_mover * 0.14)
    return max(0.0, min(100.0, low_vis + payout_fit + trust_fit - sat_penalty + early_fit))


def engagement_score(post_score: int, num_comments: int, kw_hits: int) -> float:
    return max(
        0.0,
        min(100.0, math.log1p(post_score) * 12 + math.log1p(num_comments) * 10 + kw_hits * 5),
    )


def opportunity_score(
    trust: float,
    hidden_gem: float,
    max_reward: float,
    scam_p: float,
    saturation: float,
    urgent: bool,
    kw_hits: int,
    first_mover: float = 0.0,
    mentions_count: int = 1,
    early_signal_count: int = 0,
) -> float:
    """Prioritize fresh, low-saturation edges over recycled saturated megaposts."""
    reward_fit = min(35.0, max_reward / 2.0) if max_reward else min(22.0, kw_hits * 3 + early_signal_count * 2)
    mentions_denom = max(1, mentions_count)
    freshness = min(28.0, (max_reward / mentions_denom) * 3.2) if max_reward else min(14.0, early_signal_count * 3.5)
    freshness += min(22.0, first_mover * 0.2)
    sat_penalty = saturation * (0.09 if first_mover >= 55 else 0.15)
    base = trust * 0.2 + hidden_gem * 0.26 + reward_fit + freshness
    base -= scam_p * 0.2 + sat_penalty
    if urgent:
        base += 8
    return max(0.0, min(100.0, base))


def trend_velocity_label(
    mentions_window_short: int,
    mentions_window_long: int,
) -> str:
    if mentions_window_long <= 0:
        return "unknown"
    ratio = mentions_window_short / max(1, mentions_window_long)
    if ratio >= 0.6:
        return "accelerating"
    if ratio >= 0.35:
        return "steady"
    return "slow"


def summarize_strategy(text: str, offer_type: str) -> str:
    ot = offer_type or classify_offer_type(text)
    if ot == "bank_bonus":
        return "Confirm direct-deposit rules and fee waiver; use employer or ACH push from linked bank if allowed."
    if ot == "brokerage":
        return "Complete KYC; hold minimum period if required; withdraw per promo fine print."
    if ot == "crypto_signup":
        return "Use official app/store links only; enable 2FA; verify withdrawal availability before deposit."
    if ot == "sportsbook":
        return "Check state eligibility and play-through; avoid deposit beyond promo requirement."
    return "Verify issuer domain, read promo terms, use unique email/phone per program rules."
