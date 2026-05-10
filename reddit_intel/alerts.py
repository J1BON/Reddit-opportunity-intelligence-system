"""Instant alerts — console + optional webhook + optional Discord bot channel post."""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from reddit_intel.config import (
    ALERT_WEBHOOK_URL,
    DISCORD_ALERT_CHANNEL_ID,
    DISCORD_BOT_TOKEN,
)

DISCORD_MESSAGE_LIMIT = 2000
SUMMARY_MAX_CHARS = 380


_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_EMPHASIS_RE = re.compile(r"(\*{1,3}|_{1,3})([^*_\n]+)\1")
_MD_OFFER_TAG_RE = re.compile(r"^\[[a-z_]+\]\s*", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_URL_INLINE_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _clean_summary(text: str, max_chars: int = SUMMARY_MAX_CHARS) -> str:
    """Strip HTML entities, markdown noise, and zero-width chars from Reddit body
    text so it renders cleanly in a Discord quote block."""
    if not text:
        return ""
    t = html.unescape(text)
    t = _ZERO_WIDTH_RE.sub("", t)
    t = _MD_LINK_RE.sub(r"\1", t)
    t = _MD_EMPHASIS_RE.sub(r"\2", t)
    t = _MD_OFFER_TAG_RE.sub("", t)
    # Remove inline URLs from the summary — they're redundant with the link
    # section below and cause Discord to auto-embed extra previews.
    t = _URL_INLINE_RE.sub("", t)
    t = _WHITESPACE_RE.sub(" ", t).strip()
    if len(t) > max_chars:
        cut = t[:max_chars].rsplit(" ", 1)[0]
        t = cut + "..."
    return t


def _humanize_age(first_seen_ts: float | int | None) -> str:
    if not first_seen_ts:
        return ""
    try:
        delta = max(0.0, time.time() - float(first_seen_ts))
    except (TypeError, ValueError):
        return ""
    if delta < 90:
        return "just now"
    minutes = delta / 60.0
    if minutes < 60:
        return f"{int(round(minutes))}m ago"
    hours = minutes / 60.0
    if hours < 48:
        return f"{int(round(hours))}h ago"
    days = hours / 24.0
    return f"{int(round(days))}d ago"


def _domain_of(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).hostname or url
        return host.lower().lstrip("www.")
    except (ValueError, AttributeError):
        return url


def _link_lines(reddit_links: list[str], referral_links: list[str]) -> list[str]:
    """Render the link section. Show the first Reddit URL as an unsuppressed
    link (Discord auto-embeds a single Reddit preview, which is useful);
    suppress all other URLs with <> to avoid an embed wall."""
    out: list[str] = []
    if reddit_links:
        primary = reddit_links[0]
        out.append(f"📍 Reddit · {primary}")
        for extra in reddit_links[1:3]:
            out.append(f"           · <{extra}>")
    if referral_links:
        unique: list[str] = []
        seen: set[str] = set()
        for u in referral_links:
            if not u:
                continue
            host = _domain_of(u)
            if host in seen:
                continue
            seen.add(host)
            unique.append((u, host))
            if len(unique) >= 4:
                break
        rendered = " · ".join(f"[{host}](<{u}>)" for u, host in unique)
        if rendered:
            out.append(f"🔗 Referral · {rendered}")
    return out


def _meta_line(parts: list[tuple[str, object]]) -> str:
    """Join non-empty (label, value) pairs as 'Label N' separated by ' · '."""
    rendered: list[str] = []
    for label, value in parts:
        s = "" if value is None else str(value).strip()
        if not s or s in ("0", "0.0"):
            continue
        rendered.append(f"{label} {s}")
    return " · ".join(rendered)


def _coerce_links(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(u) for u in value if u]
    if isinstance(value, str):
        # Legacy callers passed a single " | "-joined string. Split it back out.
        return [u.strip() for u in value.split("|") if u.strip()]
    return []


def format_alert(payload: dict[str, object]) -> str:
    company = str(payload.get("company_name", "") or "").strip() or "Unknown"
    reward = str(payload.get("reward_amount", "") or "").strip()
    offer_type = str(payload.get("offer_type", "") or "").strip()
    subreddit = str(payload.get("subreddit", "") or "").strip()
    age = _humanize_age(payload.get("first_seen"))

    summary = _clean_summary(str(payload.get("ai_summary", "") or ""))
    reddit_links = _coerce_links(payload.get("reddit_links") or payload.get("links"))
    referral_links = _coerce_links(payload.get("referral_links"))

    # Headline: 🔥 **Company — $XX**
    headline = company
    if reward:
        headline = f"{company} — {reward}"
    lines = [f"🔥 **{headline}**"]

    # Sub-headline: type · sub · age
    sub_parts: list[str] = []
    if offer_type:
        sub_parts.append(f"`{offer_type.replace('_', ' ')}`")
    if subreddit:
        sub_parts.append(f"r/{subreddit}")
    if age:
        sub_parts.append(age)
    if sub_parts:
        lines.append(" · ".join(sub_parts))

    # Scores line
    scores = _meta_line(
        [
            ("Trust", payload.get("trust_score")),
            ("Gem", payload.get("hidden_gem_score")),
            ("Opp", payload.get("opportunity_score")),
            ("Mentions", payload.get("mentions")),
        ]
    )
    if scores:
        lines.append(scores)

    if summary:
        lines.append("")
        lines.append(f"> {summary}")

    link_lines = _link_lines(reddit_links, referral_links)
    if link_lines:
        lines.append("")
        lines.extend(link_lines)

    return "\n".join(lines)


def format_early_gem_alert(payload: dict[str, object]) -> str:
    app = str(payload.get("app_site", "") or "Unknown").strip()
    reward = str(payload.get("reward_amount", "") or "").strip()
    age = _humanize_age(payload.get("first_seen_ts")) or str(
        payload.get("first_seen", "") or ""
    ).strip()
    subs = str(payload.get("subreddits", "") or "").strip()

    headline = f"{app} — {reward}" if reward else app
    lines = [f"💎 **EARLY GEM** · {headline}"]

    sub_parts: list[str] = []
    launch_stat = str(payload.get("launch_status", "") or "").strip()
    if launch_stat:
        sub_parts.append(f"`{launch_stat}`")
    if subs:
        # Subreddits string may be comma-joined; show first 3 cleanly.
        cleaned = ", ".join([s.strip() for s in subs.split(",") if s.strip()][:3])
        if cleaned:
            sub_parts.append(cleaned)
    if age:
        sub_parts.append(f"first seen {age}")
    if sub_parts:
        lines.append(" · ".join(sub_parts))

    scores = _meta_line(
        [
            ("First-mover", payload.get("first_mover_score")),
            ("Trust", payload.get("trust_score")),
            ("Mentions", payload.get("mentions")),
        ]
    )
    risk = str(payload.get("risk_level", "") or "").strip()
    if risk:
        scores = (scores + " · " if scores else "") + f"Risk {risk}"
    if scores:
        lines.append(scores)

    why = _clean_summary(str(payload.get("why_it_matters", "") or ""))
    pot = _clean_summary(str(payload.get("potential", "") or ""))
    if why:
        lines.append("")
        lines.append(f"> **Why** · {why}")
    if pot:
        lines.append(f"> **Potential** · {pot}")

    reddit_links = _coerce_links(payload.get("reddit_links") or payload.get("links"))
    referral_links = _coerce_links(payload.get("referral_links"))
    link_lines = _link_lines(reddit_links, referral_links)
    if link_lines:
        lines.append("")
        lines.extend(link_lines)

    return "\n".join(lines)


def format_priority_override_alert(payload: dict[str, object]) -> str:
    target = str(payload.get("target", "") or "Unknown").strip()
    reward = str(payload.get("reward_amount", "") or "").strip()
    headline = f"{target} — {reward}" if reward else target
    lines = [f"⚡ **PRIORITY** · {headline}"]

    scores = _meta_line(
        [
            ("First-mover", payload.get("first_mover_score")),
            ("Eng-accel", payload.get("engagement_acceleration_score")),
            ("Confirms", payload.get("weighted_confirmation_score")),
            ("Competition", payload.get("competition_density_score")),
            ("Mentions", payload.get("mentions")),
        ]
    )
    sat_hours = payload.get("estimated_saturation_hours_remaining")
    if sat_hours:
        scores = (scores + " · " if scores else "") + f"Sat-window {sat_hours}h"
    if scores:
        lines.append(scores)

    why = _clean_summary(str(payload.get("why", "") or ""))
    if why:
        lines.append("")
        lines.append(f"> {why}")

    reddit_links = _coerce_links(payload.get("reddit_links") or payload.get("links"))
    referral_links = _coerce_links(payload.get("referral_links"))
    link_lines = _link_lines(reddit_links, referral_links)
    if link_lines:
        lines.append("")
        lines.extend(link_lines)

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


_DISCORD_CHANNEL_TYPE_CACHE: dict[str, int] = {}

_FORUM_CHANNEL_TYPE = 15
_MEDIA_CHANNEL_TYPE = 16


def _discord_token_header(tok: str) -> str:
    return tok if tok.lower().startswith("bot ") else f"Bot {tok}"


def _discord_get_channel_type(cid: str, token_hdr: str) -> int | None:
    """Look up the Discord channel type (cached). Returns None on failure."""
    if cid in _DISCORD_CHANNEL_TYPE_CACHE:
        return _DISCORD_CHANNEL_TYPE_CACHE[cid]
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{cid}",
        headers={"Authorization": token_hdr, "User-Agent": "RedditIntelNotifier (urllib)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            info = json.loads(r.read().decode("utf-8"))
        ctype = int(info.get("type", -1))
        _DISCORD_CHANNEL_TYPE_CACHE[cid] = ctype
        return ctype
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            err_body = ""
        print(f"[discord bot] channel lookup HTTP {e.code}: {err_body}", flush=True)
        return None
    except urllib.error.URLError as e:
        print(f"[discord bot] channel lookup network error: {e}", flush=True)
        return None


def _discord_thread_title_from(text: str) -> str:
    """First non-empty line, trimmed to Discord's 100-char thread-name limit."""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line:
            return line[:100]
    return "Reddit Intel alert"


def _post_discord_message(cid: str, token_hdr: str, content: str) -> None:
    body = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{cid}/messages",
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
        print(f"[discord bot] HTTP {e.code} (POST messages): {err_body}", flush=True)
    except urllib.error.URLError as e:
        print(f"[discord bot] network error (POST messages): {e}", flush=True)


def _post_discord_forum_thread(cid: str, token_hdr: str, title: str, content: str) -> None:
    """Create a new thread in a forum/media channel with the alert as starter message."""
    body = json.dumps(
        {
            "name": title,
            "auto_archive_duration": 1440,
            "message": {"content": content},
        }
    ).encode()
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{cid}/threads",
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
        print(f"[discord bot] HTTP {e.code} (POST forum thread): {err_body}", flush=True)
    except urllib.error.URLError as e:
        print(f"[discord bot] network error (POST forum thread): {e}", flush=True)


def maybe_discord_bot_channel(text: str) -> None:
    """POST alerts into a Discord channel using a bot token.

    Auto-detects forum/media channels (type 15/16) and posts a new thread with
    the alert as the starter message; for regular text/announcement channels
    (type 0/5), posts a normal message (split into ~2000-char chunks when
    necessary).
    """
    tok = DISCORD_BOT_TOKEN
    cid = DISCORD_ALERT_CHANNEL_ID
    if not tok or not cid:
        return

    token_hdr = _discord_token_header(tok)
    ctype = _discord_get_channel_type(cid, token_hdr)

    if ctype in (_FORUM_CHANNEL_TYPE, _MEDIA_CHANNEL_TYPE):
        title = _discord_thread_title_from(text)
        # Discord forum starter messages also cap at ~2000 chars; truncate cleanly.
        first_chunk = text if len(text) <= DISCORD_MESSAGE_LIMIT else text[: DISCORD_MESSAGE_LIMIT - 20] + "\n...[truncated]"
        _post_discord_forum_thread(cid, token_hdr, title, first_chunk)
        return

    # Regular text/announcement (and threads themselves): post normally, chunked.
    for part in _discord_chunks(text):
        _post_discord_message(cid, token_hdr, part)


def notify_alert_destinations(text: str) -> None:
    """Send the same alert to webhook (if set) and Discord bot channel (if set)."""
    maybe_webhook(text)
    maybe_discord_bot_channel(text)
