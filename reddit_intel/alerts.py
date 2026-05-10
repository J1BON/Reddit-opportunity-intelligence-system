"""Instant alerts — console + optional webhook + optional Discord bot channel post."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from reddit_intel.config import (
    ALERT_WEBHOOK_URL,
    DISCORD_ALERT_CHANNEL_ID,
    DISCORD_BOT_TOKEN,
)

DISCORD_MESSAGE_LIMIT = 2000


def format_priority_override_alert(payload: dict[str, object]) -> str:
    lines = [
        "⚡ PRIORITY OVERRIDE — early signal",
        "",
        f"Target: {payload.get('target', '')}",
        f"Reward: {payload.get('reward_amount', '')}",
        f"First mover: {payload.get('first_mover_score', '')}",
        f"Engagement acceleration: {payload.get('engagement_acceleration_score', '')}",
        f"Weighted confirmations: {payload.get('weighted_confirmation_score', '')}",
        f"Competition density: {payload.get('competition_density_score', '')}",
        f"Mentions: {payload.get('mentions', '')}",
        f"Est. saturation window (h): {payload.get('estimated_saturation_hours_remaining', '')}",
        "",
        "Why:",
        str(payload.get("why", "")),
        "",
        "Links:",
        str(payload.get("links", "")),
    ]
    return "\n".join(lines)


def format_early_gem_alert(payload: dict[str, object]) -> str:
    lines = [
        "🚨 EARLY GEM DETECTED",
        "",
        f"App/Site: {payload.get('app_site', '')}",
        f"Reward: {payload.get('reward_amount', '')}",
        f"Launch Status: {payload.get('launch_status', '')}",
        f"First Seen: {payload.get('first_seen', '')}",
        f"Subreddits: {payload.get('subreddits', '')}",
        f"Mentions: {payload.get('mentions', '')}",
        f"First Mover Score: {payload.get('first_mover_score', '')}",
        f"Trust Score: {payload.get('trust_score', '')}",
        f"Risk Level: {payload.get('risk_level', '')}",
        "",
        "Why It Matters:",
        str(payload.get("why_it_matters", "")),
        "",
        "Potential:",
        str(payload.get("potential", "")),
        "",
        "Links:",
        str(payload.get("links", "")),
    ]
    return "\n".join(lines)


def format_alert(payload: dict[str, object]) -> str:
    lines = [
        "🔥 NEW USA OPPORTUNITY",
        "",
        f"Company: {payload.get('company_name', '')}",
        f"Reward: {payload.get('reward_amount', '')}",
        f"Requirements: {payload.get('requirements', '')}",
        f"Deposit Needed: {payload.get('deposit_needed', '')}",
        f"States Eligible: {payload.get('states', '')}",
        f"Trust Score: {payload.get('trust_score', '')}",
        f"Mentions: {payload.get('mentions', '')}",
        f"Trend Velocity: {payload.get('trend_velocity', '')}",
        f"Hidden Gem Score: {payload.get('hidden_gem_score', '')}",
        "",
        "Summary:",
        str(payload.get("ai_summary", "")),
        "",
        "Links:",
        str(payload.get("links", "")),
    ]
    return "\n".join(lines)


def send_console_alert(text: str) -> None:
    print("\n" + "=" * 60 + "\n" + text + "\n" + "=" * 60 + "\n")


def maybe_webhook(text: str) -> None:
    if not ALERT_WEBHOOK_URL:
        return
    body = json.dumps({"content": text[:1900]}).encode()
    req = urllib.request.Request(
        ALERT_WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except urllib.error.URLError:
        pass


def _discord_chunks(text: str, limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    """Discord allows max ~2000 chars per message content."""
    t = text or ""
    if len(t) <= limit:
        return [t] if t else []
    parts: list[str] = []
    i = 0
    while i < len(t):
        chunk = t[i : i + limit]
        parts.append(chunk)
        i += limit
    return parts


def maybe_discord_bot_channel(text: str) -> None:
    """POST alerts into a server channel using a Discord Bot token (Bot REST API)."""
    tok = DISCORD_BOT_TOKEN
    cid = DISCORD_ALERT_CHANNEL_ID
    if not tok or not cid:
        return
    url = f"https://discord.com/api/v10/channels/{cid}/messages"
    token_hdr = tok if tok.lower().startswith("bot ") else f"Bot {tok}"

    for part in _discord_chunks(text):
        body = json.dumps({"content": part}).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": token_hdr,
                "Content-Type": "application/json",
                "User-Agent": "RedditIntelNotifier (urllib)",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=20)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                err_body = ""
            print(f"[discord bot] HTTP {e.code}: {err_body}", flush=True)
        except urllib.error.URLError as e:
            print(f"[discord bot] network error: {e}", flush=True)


def notify_alert_destinations(text: str) -> None:
    """Send the same alert to webhook (if set) and Discord bot channel (if set)."""
    maybe_webhook(text)
    maybe_discord_bot_channel(text)
