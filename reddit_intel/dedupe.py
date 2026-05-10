"""Aggressive duplicate collapse: canonical IDs from brand + URL host + amount bucket."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

from reddit_intel.detectors import extract_money_amounts, extract_urls


_BRAND_ALIASES: dict[str, str] = {
    "so fi": "SOFI",
    "sofi": "SOFI",
    "chime": "CHIME",
    "webull": "WEBULL",
    "robinhood": "ROBINHOOD",
    "coinbase": "COINBASE",
    "draftkings": "DRAFTKINGS",
    "fanduel": "FANDUEL",
    "betmgm": "BETMGM",
    "capital one": "CAPITAL_ONE",
    "chase": "CHASE",
    "wells fargo": "WELLS_FARGO",
    "discover": "DISCOVER",
    "cash app": "CASH_APP",
    "cashapp": "CASH_APP",
    "current": "CURRENT",
    "upgrade": "UPGRADE",
    "acorns": "ACORNS",
    "stash": "STASH",
}


def normalize_text_blob(title: str, body: str) -> str:
    return f"{title}\n{body or ''}".strip()


def guess_company_slug(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").lower())
    for alias, slug in sorted(_BRAND_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in t:
            return slug
    # Fallback: first capitalized token-looking brand from title
    title_line = (text or "").split("\n")[0]
    m = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", title_line)
    if m:
        return re.sub(r"\s+", "_", m.group(1).upper())
    return "UNKNOWN_BRAND"


def primary_link_host(text: str) -> str:
    urls = extract_urls(text)
    for u in urls:
        try:
            host = (urlparse(u).hostname or "").lower()
            if host.endswith("reddit.com"):
                continue
            return host.replace("www.", "")
        except Exception:
            continue
    return ""


def amount_bucket(amounts: list[float]) -> str:
    if not amounts:
        return "NA"
    m = max(amounts)
    return str(int(round(m)))


def build_canonical_offer_id(title: str, body: str, offer_type: str) -> str:
    blob = normalize_text_blob(title, body)
    brand = guess_company_slug(blob)
    host = primary_link_host(blob)
    bucket = amount_bucket(extract_money_amounts(blob))
    raw = f"{brand}|{offer_type}|{host}|{bucket}"
    h = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{brand}_{offer_type}_{bucket}_{h}".upper().replace(" ", "_")


def merge_unique_lists(*lists: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        for x in lst:
            k = x.strip()
            if k and k not in seen:
                seen.add(k)
                out.append(k)
    return out
