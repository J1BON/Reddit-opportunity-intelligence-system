"""Keyword, payout confirmation, urgency, scam — rule-based signals."""

from __future__ import annotations

import re
from reddit_intel.config import (
    EARLY_SIGNAL_PHRASES,
    KEYWORD_PHRASES,
    PAYOUT_CONFIRMATION_PHRASES,
    SCAM_DOMAINS_HINTS,
    SCAM_SIGNAL_PHRASES,
    URGENCY_PHRASES,
    USA_BOOST_TERMS,
    USA_PENALTY_TERMS,
)


def _lower(text: str) -> str:
    return (text or "").lower()


def keyword_hit_count(text: str) -> int:
    t = _lower(text)
    return sum(1 for k in KEYWORD_PHRASES if k in t)


def payout_confirmation_hits(text: str) -> list[str]:
    t = _lower(text)
    return [p for p in PAYOUT_CONFIRMATION_PHRASES if p in t]


def urgency_hits(text: str) -> list[str]:
    t = _lower(text)
    return [p for p in URGENCY_PHRASES if p in t]


def early_signal_hits(text: str) -> list[str]:
    t = _lower(text)
    return [p for p in EARLY_SIGNAL_PHRASES if p in t]


def early_signal_hit_count(text: str) -> int:
    return len(early_signal_hits(text))


def scam_signals(text: str) -> list[str]:
    t = _lower(text)
    hits = [p for p in SCAM_SIGNAL_PHRASES if p in t]
    for d in SCAM_DOMAINS_HINTS:
        if d in t:
            hits.append(d)
    return hits


def usa_boost_score(text: str) -> float:
    t = _lower(text)
    boost = sum(2 for term in USA_BOOST_TERMS if term in t)
    penalty = sum(5 for term in USA_PENALTY_TERMS if term in t)
    return max(0.0, min(40.0, boost - penalty))


_MONEY_RE = re.compile(
    r"(?:\$|usd\s*)[\s]*([\d,]+(?:\.\d{1,2})?)|(?:earn|get|receive|bonus)\s*(?:of\s*)?\$?\s*([\d,]+(?:\.\d{1,2})?)",
    re.I,
)


def extract_money_amounts(text: str) -> list[float]:
    out: list[float] = []
    for m in _MONEY_RE.finditer(text or ""):
        g = m.group(1) or m.group(2)
        if g:
            try:
                out.append(float(g.replace(",", "")))
            except ValueError:
                continue
    return out


_URL_RE = re.compile(r"https?://[^\s\]>\"\)]+", re.I)


def extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text or "")


def classify_offer_type(text: str) -> str:
    t = _lower(text)
    if any(x in t for x in ("bank bonus", "checking", "savings bonus", "direct deposit")):
        return "bank_bonus"
    if any(x in t for x in ("sportsbook", "free bet", "draftkings", "fanduel", "betmgm")):
        return "sportsbook"
    if any(x in t for x in ("brokerage", "free stock", "webull", "robinhood")):
        return "brokerage"
    if any(x in t for x in ("crypto", "coinbase", "exchange")):
        return "crypto_signup"
    if "referral" in t or "invite" in t:
        return "referral"
    if "cashback" in t:
        return "cashback"
    return "general_signup"


def subreddit_priority(sub: str) -> int:
    from reddit_intel.config import EXCLUDED_SUBREDDITS, HIGH_PRIORITY_SUBREDDITS, MEDIUM_PRIORITY_SUBREDDITS

    s = sub.lower()
    if s in {x.lower() for x in EXCLUDED_SUBREDDITS}:
        return -1
    if s in {x.lower() for x in HIGH_PRIORITY_SUBREDDITS}:
        return 2
    if s in {x.lower() for x in MEDIUM_PRIORITY_SUBREDDITS}:
        return 1
    return 0


def mentions_increment(existing: int, weight: int = 1) -> int:
    return existing + weight
