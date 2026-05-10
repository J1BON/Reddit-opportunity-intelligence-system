"""Fresh domains, unknown brands, first-mover and legitimacy heuristics (no external WHOIS)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from reddit_intel.config import KNOWN_BRAND_SLUGS

_SKIP_HOST_SUFFIXES = (
    "reddit.com",
    "redd.it",
    "imgur.com",
    "github.com",
    "youtube.com",
    "youtu.be",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "linkedin.com",
    "discord.gg",
    "discord.com",
    "google.com",
    "play.google.com",
    "apps.apple.com",
    "apple.com",
)


def is_known_brand_slug(slug: str) -> bool:
    s = (slug or "").strip().upper().replace(" ", "_")
    return s in KNOWN_BRAND_SLUGS


def extract_external_domains(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        try:
            host = (urlparse(u).hostname or "").lower().replace("www.", "")
            if not host or "." not in host:
                continue
            if any(host == s or host.endswith("." + s) for s in _SKIP_HOST_SUFFIXES):
                continue
            if host not in seen:
                seen.add(host)
                out.append(host)
        except Exception:
            continue
    return out


def domain_age_estimate_heuristic(domain: str) -> str:
    """Rough tier without WHOIS — flags common startup / referral patterns."""
    d = (domain or "").lower()
    if not d:
        return "unknown"
    if d.count(".") >= 3:
        return "deep_subdomain_often_partner_or_white_label"
    if any(d.endswith(t) for t in (".io", ".app", ".xyz", ".fun", ".click")):
        return "often_early_stage_tld_verify_whois"
    if "invite" in d or "beta" in d or "early" in d:
        return "invite_or_beta_host_verify_official"
    if any(x in d for x in ("ref", "refer", "aff", "goto", "clk", "tracking")):
        return "affiliate_or_tracking_host_common"
    if d.endswith(".com"):
        return "standard_tld_still_verify_registration"
    return "unknown_verify_via_whois"


def affiliate_system_hint(domain: str) -> bool:
    d = (domain or "").lower()
    return any(x in d for x in ("affiliate", "aff-", "_aff", "refer", "ref=", "goto.", "clk.", "tracking"))


def launch_status_label(text: str, early_signal_count: int, is_unknown: bool, domain_first_ever: bool) -> str:
    parts: list[str] = []
    if domain_first_ever:
        parts.append("first_seen_domain")
    if is_unknown:
        parts.append("unknown_brand_or_startup_name")
    if early_signal_count >= 3:
        parts.append("strong_early_launch_signals")
    elif early_signal_count >= 1:
        parts.append("early_launch_language")
    else:
        parts.append("no_early_language_detected")
    blob = (text or "").lower()
    if any(x in blob for x in ("invite only", "invite-only", "invite only")):
        parts.append("invite_only_mentioned")
    if "beta" in blob:
        parts.append("beta_mentioned")
    if "soft launch" in blob or "soft-launch" in blob:
        parts.append("soft_launch")
    return "; ".join(parts)


def startup_legitimacy_score(
    text: str,
    domains: list[str],
    scam_p: float,
    confirmation_count: int,
    early_signal_count: int,
    has_https_links: bool,
) -> float:
    """0–100 plausibility — rule-based, not a substitute for due diligence."""
    t = (text or "").lower()
    score = 42.0
    if has_https_links:
        score += 8
    if "apps.apple.com" in t or "play.google.com" in t or "app store" in t:
        score += 14
    if any(dom.endswith(".com") for dom in domains):
        score += 6
    if confirmation_count:
        score += min(22.0, confirmation_count * 5.0)
    if early_signal_count >= 2:
        score += min(10.0, early_signal_count * 3.0)
    score -= scam_p * 0.35
    if any(x in t for x in ("mlm", "downline", "recruit", "team volume")):
        score -= 18
    if "telegram" in t and "admin" in t:
        score -= 12
    return max(0.0, min(100.0, score))


def first_mover_score(
    saturation: float,
    max_reward_usd: float,
    mentions_count: int,
    is_unknown_entity: bool,
    early_signal_count: int,
    domain_is_first_seen_ever: bool,
    trend_velocity: str,
    engagement_score_val: float,
    startup_legitimacy: float,
) -> float:
    """0–100 first-mover / early-arbitrage signal."""
    low_sat = max(0.0, 100.0 - saturation)
    reward_per_mention = max_reward_usd / max(1, mentions_count) if max_reward_usd else 0.0
    reward_fit = min(35.0, reward_per_mention * 4.0)

    unknown_boost = 18.0 if is_unknown_entity else 0.0
    domain_boost = 14.0 if domain_is_first_seen_ever else 0.0
    early_boost = min(28.0, early_signal_count * 7.0)

    trend_boost = 0.0
    if trend_velocity == "accelerating":
        trend_boost = 12.0
    elif trend_velocity == "steady":
        trend_boost = 6.0

    eng_fit = min(15.0, engagement_score_val * 0.12)
    legit_fit = startup_legitimacy * 0.18

    raw = (
        low_sat * 0.28
        + reward_fit
        + unknown_boost
        + domain_boost
        + early_boost
        + trend_boost
        + eng_fit
        + legit_fit
    )
    return max(0.0, min(100.0, raw))


def saturation_risk_score(
    trend_velocity: str,
    mentions_count: int,
    early_signal_count: int,
    current_saturation: float,
) -> float:
    """0–100 likelihood offer becomes crowded soon."""
    risk = 25.0
    if trend_velocity == "accelerating":
        risk += 28.0
    elif trend_velocity == "steady":
        risk += 14.0
    risk += min(25.0, mentions_count * 3.5)
    risk += min(15.0, early_signal_count * 4.0)
    risk -= current_saturation * 0.15
    return max(0.0, min(100.0, risk))


def predicted_growth_score(
    trend_velocity: str,
    early_signal_count: int,
    engagement_score_val: float,
    subreddit_spread: int,
    max_reward_usd: float,
) -> float:
    """0–100 heuristic viral / acquisition-spend trajectory."""
    g = 22.0
    if trend_velocity == "accelerating":
        g += 28.0
    elif trend_velocity == "steady":
        g += 14.0
    g += min(22.0, early_signal_count * 5.5)
    g += min(18.0, subreddit_spread * 6.0)
    g += min(20.0, engagement_score_val * 0.14)
    g += min(18.0, max_reward_usd / 5.0) if max_reward_usd else 0.0
    return max(0.0, min(100.0, g))


_PROFIT_WINDOW_RE = re.compile(
    r"(limited time|expires?|deadline|ending|first\s+\d+|hours?\s+left|today only|tonight)",
    re.I,
)


def estimated_profit_window(
    urgency: bool,
    saturation_risk: float,
    predicted_growth: float,
    text: str,
) -> str:
    """Human-readable window hint."""
    t = text or ""
    urgent_lang = bool(_PROFIT_WINDOW_RE.search(t)) or urgency
    if saturation_risk >= 70 and predicted_growth >= 60:
        return "narrow_window_act_fast_likely_saturates"
    if urgent_lang and saturation_risk >= 55:
        return "days_to_weeks_promo_language_suggests_short_tail"
    if predicted_growth >= 65 and saturation_risk < 55:
        return "weeks_to_months_possible_acquisition_campaign_watch_terms"
    if saturation_risk < 40 and predicted_growth < 45:
        return "uncertain_extended_or_low_velocity_monitor_mentions"
    return "evaluate_case_by_case_verify_expiry"


def early_gem_explanation(
    company: str,
    first_mover: float,
    is_unknown: bool,
    domain_first: bool,
    saturation: float,
    legitimacy: float,
) -> tuple[str, str]:
    """Why it matters + potential — template 'AI' explanation."""
    why = (
        f"{company}: first_mover={first_mover:.0f}, saturation={saturation:.0f}. "
        f"{'Unknown brand — possible pre-mainstream campaign. ' if is_unknown else ''}"
        f"{'First-seen referral domain in corpus. ' if domain_first else ''}"
        f"Legitimacy heuristic={legitimacy:.0f}/100 (not investment advice; verify)."
    )
    pot = (
        "If terms are real and caps are uncrowded, early referral windows can outperform "
        "recycled mega-offers before support queues and eligibility tighten. "
        "Watch for sudden mention spikes (saturation risk)."
    )
    return why, pot
