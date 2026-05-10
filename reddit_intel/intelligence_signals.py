"""Phrase banks and heuristic scores: sentiment, states, stacking, fatigue, competition."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

NEGATIVE_PAYOUT_PHRASES = [
    "didn't get paid",
    "did not get paid",
    "never got paid",
    "no payout",
    "not paid",
    "account banned",
    "banned",
    "withdrawal pending",
    "pending withdrawal",
    "still pending",
    "support ignored",
    "no response from support",
    "bonus denied",
    "denied the bonus",
    "denied bonus",
    "scam",
    "not worth it",
    "waste of time",
    "didn't work",
    "doesn't work",
    "frozen funds",
    "locked funds",
    "can't withdraw",
    "cannot withdraw",
]

WITHDRAWAL_FRICTION_PHRASES = [
    "withdrawal pending",
    "slow payout",
    "delayed payout",
    "minimum cashout",
    "minimum withdrawal",
    "kyc hold",
    "verification stuck",
    "identity verification",
    "can't withdraw",
    "cannot withdraw",
    "locked balance",
]

TEMPORARY_BOOST_PHRASES = [
    "boosted reward",
    "double referral",
    "enhanced payout",
    "limited enhanced",
    "this week only bonus",
    "double bonus",
    "increased payout",
    "elevated bonus",
]

RECURRING_PROMO_PHRASES = [
    "every month",
    "monthly bonus",
    "each month",
    "seasonal promo",
    "rotating bonus",
    "weekly promo",
    "reload bonus",
    "ongoing promotion",
]

STACKING_HINT_PHRASES = [
    "stack with",
    "combine with",
    "bank bonus",
    "brokerage",
    "ach trigger",
    "two banks",
    "matched deposit",
    "cashback stack",
    "hedge",
]

_US_ABBREV = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()

_US_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_US_ABBREV, key=len, reverse=True)) + r")\b",
    re.I,
)

_EXCLUDED_STATES_RE = re.compile(
    r"(?:exclude|excluding|not(?:\s+)?available(?:\s+)?in|blocked\s+in|except)\s+([A-Z]{2}(?:\s*,\s*[A-Z]{2})*)",
    re.I,
)


def negative_sentiment_hits(text: str) -> list[str]:
    t = (text or "").lower()
    return [p for p in NEGATIVE_PAYOUT_PHRASES if p in t]


def withdrawal_friction_hits(text: str) -> list[str]:
    t = (text or "").lower()
    return [p for p in WITHDRAWAL_FRICTION_PHRASES if p in t]


def temporary_boost_hits(text: str) -> list[str]:
    t = (text or "").lower()
    return [p for p in TEMPORARY_BOOST_PHRASES if p in t]


def recurring_promo_hits(text: str) -> list[str]:
    t = (text or "").lower()
    return [p for p in RECURRING_PROMO_PHRASES if p in t]


def stacking_hint_hits(text: str) -> list[str]:
    t = (text or "").lower()
    return [p for p in STACKING_HINT_PHRASES if p in t]


def extract_us_states_mentioned(text: str) -> tuple[list[str], list[str]]:
    """Return (eligible-ish mentions, excluded mentions from simple patterns)."""
    blob = text or ""
    found = sorted(set(m.upper() for m in _US_PATTERN.findall(blob)))
    excluded: list[str] = []
    for m in _EXCLUDED_STATES_RE.finditer(blob):
        chunk = m.group(1) or ""
        excluded.extend(x.strip().upper() for x in chunk.split(",") if len(x.strip()) == 2)
    excluded = sorted(set(excluded))
    return found, excluded


def state_coverage_score(eligible_states: list[str], excluded_states: list[str]) -> float:
    """0–100 heuristic: broader legal footprint boosts score."""
    if not eligible_states and not excluded_states:
        return 35.0
    net = max(0, len(set(eligible_states)) - len(set(excluded_states)))
    base = min(70.0, net * 12.0)
    if excluded_states:
        base -= min(40.0, len(set(excluded_states)) * 8.0)
    return max(0.0, min(100.0, base + 20.0))


def referral_link_dup_ratio(urls: list[str]) -> float:
    """0–1 fraction of URLs that are duplicates (crowded referral posts)."""
    if not urls:
        return 0.0
    norm = [_normalize_ref_url(u) for u in urls]
    c = Counter(norm)
    if not norm:
        return 0.0
    dups = sum(v for v in c.values() if v > 1)
    return min(1.0, dups / max(1, len(norm)))


def _normalize_ref_url(u: str) -> str:
    u = (u or "").split("?")[0].split("#")[0].rstrip("/").lower()
    return u[:500]


def competition_density_score(
    unique_posters: int,
    mention_posts: int,
    referral_urls: list[str],
) -> float:
    """0–100 higher = more crowded referral competition."""
    if mention_posts <= 0:
        mention_posts = 1
    poster_ratio = unique_posters / mention_posts
    dup_ratio = referral_link_dup_ratio(referral_urls)
    density = (1.0 - poster_ratio) * 45.0 + dup_ratio * 55.0 + min(40.0, (mention_posts - 1) * 4.0)
    return max(0.0, min(100.0, density))


def engagement_acceleration_score(
    post_score: int,
    num_comments: int,
    post_age_hours: float,
    subreddit_spread: int,
    trend_velocity: str,
) -> float:
    """Unusual early velocity proxy (0–100)."""
    t_h = max(1.0 / 60.0, post_age_hours)
    v_score = post_score / t_h
    v_comm = num_comments / t_h
    raw = math.log1p(v_score) * 18.0 + math.log1p(v_comm) * 14.0 + min(25.0, subreddit_spread * 5.0)
    if trend_velocity == "accelerating":
        raw += 14.0
    elif trend_velocity == "steady":
        raw += 7.0
    return max(0.0, min(100.0, raw))


def estimated_saturation_hours_remaining(
    saturation_score_val: float,
    saturation_risk: float,
    mention_growth_per_hour: float,
) -> float:
    """Rough hours until heavily saturated; bounded."""
    base = 72.0 * (1.0 - saturation_score_val / 130.0) * (1.0 - saturation_risk / 130.0)
    if mention_growth_per_hour > 8:
        base *= 0.55
    elif mention_growth_per_hour > 3:
        base *= 0.75
    return max(4.0, min(720.0, base))


def fatigue_score(
    saturation: float,
    mentions: int,
    complaint_score: float,
    competition_density: float,
) -> float:
    """Offer exhaustion / overexposure (0–100)."""
    f = saturation * 0.35 + min(35.0, (mentions - 1) * 2.5)
    f += complaint_score * 0.25 + competition_density * 0.18
    return max(0.0, min(100.0, f))


def complaint_score_from_rates(
    negative_comment_lines: int,
    withdrawal_lines: int,
    comments_sampled: int,
    body_negative_hits: int,
) -> float:
    """Aggregate complaint intensity 0–100."""
    denom = max(1, comments_sampled)
    thread_rate = (negative_comment_lines + withdrawal_lines * 0.8) / denom
    body_boost = min(40.0, body_negative_hits * 12.0)
    return max(0.0, min(100.0, thread_rate * 85.0 + body_boost))


def payout_failure_rate(
    negative_comment_lines: int,
    comments_sampled: int,
) -> float:
    """0–100 proportion-like."""
    if comments_sampled <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * negative_comment_lines / comments_sampled))


def withdrawal_friction_score(thread_hits: int, comments_sampled: int, body_hits: int) -> float:
    base = min(50.0, body_hits * 14.0)
    if comments_sampled > 0:
        base += min(50.0, (thread_hits / comments_sampled) * 70.0)
    return max(0.0, min(100.0, base))


def recurring_bonus_probability(text: str) -> float:
    return min(100.0, len(recurring_promo_hits(text)) * 28.0)


def temporary_boost_score(text: str) -> float:
    return min(100.0, len(temporary_boost_hits(text)) * 22.0 + min(40.0, len(temporary_boost_hits(text)) * 5.0))


def stackability_score(text: str, offer_type: str) -> float:
    base = min(80.0, len(stacking_hint_hits(text)) * 18.0)
    if offer_type in ("bank_bonus", "brokerage", "crypto_signup"):
        base += 12.0
    return max(0.0, min(100.0, base))


def estimated_maximized_reward_hint(max_reward: float, stack_score: float, boost_score: float) -> str:
    if max_reward <= 0:
        return "unknown_base_explore_stack_and_boost_keywords"
    lift = 1.0 + stack_score / 250.0 + boost_score / 300.0
    est = max_reward * lift
    return f"~${est:.0f}_heuristic_combined_{max_reward:g}_base"


def weighted_confirmation_score_norm(
    weighted_positive_sum: float,
    repetitive_penalty: float,
    comments_sampled: int,
) -> float:
    """Map cumulative weights to 0–100."""
    if comments_sampled <= 0:
        return 0.0
    adj = max(0.0, weighted_positive_sum - repetitive_penalty)
    return max(0.0, min(100.0, 12.0 * math.log1p(adj)))


def offer_integrity_score_from_probe(ok: bool | None, timeout: bool = False) -> float:
    """HTTP probe result → 0–100; None = unknown neutral."""
    if ok is True:
        return 88.0
    if ok is False:
        return 22.0
    if timeout:
        return 55.0
    return 72.0


def apply_daily_learning_adjustments(
    trust_base: float,
    scam_p: float,
    subreddit_quality: float,
    subreddit_decay: float,
) -> tuple[float, float, float]:
    """Returns (adjusted_trust, learning_trust_delta, learning_scam_delta)."""
    t_adj = (subreddit_quality - 50.0) * 0.08
    d_pen = subreddit_decay * 0.12
    trust_new = trust_base + t_adj - d_pen
    scam_adj = -(subreddit_quality - 50.0) * 0.04 + subreddit_decay * 0.06
    scam_new = max(0.0, min(100.0, scam_p + scam_adj))
    trust_new = max(0.0, min(100.0, trust_new))
    delta_t = trust_new - trust_base
    delta_s = scam_new - scam_p
    return trust_new, delta_t, delta_s


def unique_authors_from_sources(sources: list[dict[str, Any]]) -> int:
    authors = set()
    for s in sources:
        if not isinstance(s, dict):
            continue
        a = (s.get("author") or "").strip()
        if a and a.lower() not in ("none", "[deleted]"):
            authors.add(a.lower())
    return len(authors)


def merge_eligible_states_json(existing_json: str | None, text: str) -> str:
    import json

    prev: list[str] = []
    if existing_json:
        try:
            v = json.loads(existing_json)
            if isinstance(v, list):
                prev = [str(x).upper() for x in v]
        except json.JSONDecodeError:
            prev = []
    found, _ex = extract_us_states_mentioned(text)
    merged = sorted(set(prev + found))
    return json.dumps(merged)


def merge_excluded_states_json(existing_json: str | None, text: str) -> str:
    import json

    prev: list[str] = []
    if existing_json:
        try:
            v = json.loads(existing_json)
            if isinstance(v, list):
                prev = [str(x).upper() for x in v]
        except json.JSONDecodeError:
            prev = []
    _f, ex = extract_us_states_mentioned(text)
    merged = sorted(set(prev + ex))
    return json.dumps(merged)
