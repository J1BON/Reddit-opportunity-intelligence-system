"""Aggressive duplicate collapse + accurate brand / title display.

This module is responsible for two related things:
- Building a stable ``canonical_offer_id`` so the same offer reposted across
  subs collapses into one row.
- Recovering a clean human-friendly brand + post title for display in the
  dashboard and Discord alerts. Reddit titles are messy ([tag] prefixes,
  zero-width chars, ALL CAPS spam, etc.) so this lives here.

Brand-pick rules (in priority order):
1. Primary external URL host maps to a known brand domain.
2. The Reddit post title contains an *unambiguous* brand name
   (e.g. "Bybit", "OnePay", "Chime", "Simplii"). Match with word boundaries
   so "currently" never matches "Current".
3. The post body contains an unambiguous brand name (word-boundary).
4. The title contains an *ambiguous* brand word ("Chase", "Current",
   "Discover", "Upgrade", "Stash", "Public", "Marcus", "Dave"...) that is
   capitalized in the original title (i.e. used as a proper noun).
5. Fallback: first capitalized noun-phrase from the cleaned title.
6. ``UNKNOWN_BRAND``.

This is intentionally a heuristic — it will never beat a hand-labelled
gazetteer, but it's good enough that "chase a new side hustle" stops
turning into a fictional Chase offer.
"""

from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import urlparse

from reddit_intel.detectors import extract_money_amounts, extract_urls


# ----------------------------------------------------------------------
# Brand dictionaries
# ----------------------------------------------------------------------

# Brand identified by primary external domain. Most reliable signal.
_BRAND_DOMAIN_MAP: dict[str, str] = {
    "chase.com": "CHASE",
    "current.com": "CURRENT",
    "chime.com": "CHIME",
    "sofi.com": "SOFI",
    "webull.com": "WEBULL",
    "robinhood.com": "ROBINHOOD",
    "coinbase.com": "COINBASE",
    "draftkings.com": "DRAFTKINGS",
    "fanduel.com": "FANDUEL",
    "betmgm.com": "BETMGM",
    "capitalone.com": "CAPITAL_ONE",
    "wellsfargo.com": "WELLS_FARGO",
    "discover.com": "DISCOVER",
    "cash.app": "CASH_APP",
    "cashapp.com": "CASH_APP",
    "upgrade.com": "UPGRADE",
    "acorns.com": "ACORNS",
    "stash.com": "STASH",
    "stashinvest.com": "STASH",
    "bybit.com": "BYBIT",
    "bybit.eu": "BYBIT",
    "partner.bybit.com": "BYBIT",
    "onepay.com": "ONEPAY",
    "onepayfin.com": "ONEPAY",
    "static.one.app": "ONEPAY",
    "one.app": "ONEPAY",
    "simplii.com": "SIMPLII",
    "ally.com": "ALLY_BANK",
    "klarna.com": "KLARNA",
    "affirm.com": "AFFIRM",
    "revolut.com": "REVOLUT",
    "monzo.com": "MONZO",
    "n26.com": "N26",
    "bilt.com": "BILT",
    "biltrewards.com": "BILT",
    "plynk.com": "PLYNK",
    "fold.app": "FOLD",
    "crypto.com": "CRYPTO_COM",
    "kraken.com": "KRAKEN",
    "gemini.com": "GEMINI",
    "binance.com": "BINANCE",
    "binance.us": "BINANCE",
    "kucoin.com": "KUCOIN",
    "okx.com": "OKX",
    "bitget.com": "BITGET",
    "bitstamp.net": "BITSTAMP",
    "bitfinex.com": "BITFINEX",
    "m1.com": "M1_FINANCE",
    "m1finance.com": "M1_FINANCE",
    "marcus.com": "MARCUS",
    "citi.com": "CITI",
    "citibank.com": "CITI",
    "bmo.com": "BMO",
    "bmoharris.com": "BMO",
    "usbank.com": "US_BANK",
    "key.com": "KEYBANK",
    "keybank.com": "KEYBANK",
    "truist.com": "TRUIST",
    "pnc.com": "PNC",
    "hsbc.com": "HSBC",
    "varo.com": "VARO",
    "dave.com": "DAVE",
    "albert.com": "ALBERT",
    "albertapp.com": "ALBERT",
    "moneylion.com": "MONEYLION",
    "empower.com": "EMPOWER",
    "earnin.com": "EARNIN",
    "brigit.com": "BRIGIT",
    "kashable.com": "KASHABLE",
    "publicapp.com": "PUBLIC",
    "public.com": "PUBLIC",
    "betterment.com": "BETTERMENT",
    "wealthfront.com": "WEALTHFRONT",
    "yotta.com": "YOTTA",
    "tellerapp.com": "TELLER",
    "swagbucks.com": "SWAGBUCKS",
    "inboxdollars.com": "INBOXDOLLARS",
    "rakuten.com": "RAKUTEN",
    "fetch.com": "FETCH",
    "ibotta.com": "IBOTTA",
    "shopkick.com": "SHOPKICK",
    "drop.com": "DROP",
    "honeygain.com": "HONEYGAIN",
    "mistplay.com": "MISTPLAY",
    "junodash.com": "JUNO",
    "juno.com": "JUNO",
    "mercury.com": "MERCURY",
}


# Brand names that are *unambiguous* — they don't collide with common
# English words, so we can match anywhere (title or body) with simple
# word-boundary regex.
_UNAMBIGUOUS_BRANDS: dict[str, str] = {
    "sofi": "SOFI",
    "so fi": "SOFI",
    "chime": "CHIME",
    "webull": "WEBULL",
    "robinhood": "ROBINHOOD",
    "coinbase": "COINBASE",
    "draftkings": "DRAFTKINGS",
    "fanduel": "FANDUEL",
    "betmgm": "BETMGM",
    "capital one": "CAPITAL_ONE",
    "wells fargo": "WELLS_FARGO",
    "cash app": "CASH_APP",
    "cashapp": "CASH_APP",
    "acorns": "ACORNS",
    "bybit": "BYBIT",
    "onepay": "ONEPAY",
    "one pay": "ONEPAY",
    "simplii": "SIMPLII",
    "ally bank": "ALLY_BANK",
    "klarna": "KLARNA",
    "affirm": "AFFIRM",
    "revolut": "REVOLUT",
    "monzo": "MONZO",
    "n26": "N26",
    "bilt rewards": "BILT",
    "biltrewards": "BILT",
    "plynk": "PLYNK",
    "crypto.com": "CRYPTO_COM",
    "kraken": "KRAKEN",
    "gemini exchange": "GEMINI",
    "binance us": "BINANCE",
    "binance.us": "BINANCE",
    "binance": "BINANCE",
    "kucoin": "KUCOIN",
    "bitget": "BITGET",
    "okx": "OKX",
    "m1 finance": "M1_FINANCE",
    "wealthfront": "WEALTHFRONT",
    "betterment": "BETTERMENT",
    "varo": "VARO",
    "moneylion": "MONEYLION",
    "empower": "EMPOWER",
    "earnin": "EARNIN",
    "brigit": "BRIGIT",
    "kashable": "KASHABLE",
    "swagbucks": "SWAGBUCKS",
    "inboxdollars": "INBOXDOLLARS",
    "rakuten": "RAKUTEN",
    "ibotta": "IBOTTA",
    "shopkick": "SHOPKICK",
    "honeygain": "HONEYGAIN",
    "mistplay": "MISTPLAY",
    "yotta savings": "YOTTA",
    "us bank": "US_BANK",
    "u.s. bank": "US_BANK",
    "keybank": "KEYBANK",
    "key bank": "KEYBANK",
    "truist": "TRUIST",
    "citibank": "CITI",
    "wise.com": "WISE",
    "transferwise": "WISE",
}


# Brand names that collide with common English. Only count them as a brand
# match if they appear *capitalized in the original title text* — i.e. used
# as a proper noun ("Open a Chase account") and not as a verb / adjective
# ("chase a new side hustle", "current revenue").
_AMBIGUOUS_BRANDS: dict[str, str] = {
    "chase": "CHASE",
    "current": "CURRENT",
    "discover": "DISCOVER",
    "stash": "STASH",
    "upgrade": "UPGRADE",
    "public": "PUBLIC",
    "marcus": "MARCUS",
    "dave": "DAVE",
    "albert": "ALBERT",
    "fold": "FOLD",
    "mercury": "MERCURY",
    "fetch": "FETCH",
    "drop": "DROP",
    "juno": "JUNO",
    "teller": "TELLER",
    "ally": "ALLY_BANK",
    "citi": "CITI",
    "bmo": "BMO",
    "pnc": "PNC",
    "hsbc": "HSBC",
    "gemini": "GEMINI",
}


# Stopwords that should never be used as a fallback brand even if they're
# the first capitalized word in a title.
_FALLBACK_STOPWORDS: frozenset[str] = frozenset(
    {
        "hi", "hello", "hey", "looking", "need", "want", "wanted", "help",
        "anyone", "anybody", "someone", "people", "guys", "free", "easy",
        "best", "top", "new", "just", "open", "the", "this", "that", "got",
        "get", "got_a", "found", "found_a", "i", "im", "my", "we", "they",
        "you", "he", "she", "today", "today_only", "now", "tonight",
        "any", "any_one", "what", "where", "when", "why", "how", "who",
        "is", "are", "do", "does", "did", "can", "could", "would", "should",
        "please", "thanks", "thank", "wow", "yo", "lol", "rip",
        "offer", "referral", "referrals", "promo", "promos", "deal", "deals",
        "code", "codes", "bonus", "bonuses", "signup", "sign", "up",
    }
)


# Words that suggest a financial context near an ambiguous brand-word
# (used as a secondary check, currently kept loose since the primary
# disambiguation is "must be capitalized in title").
_FIN_CONTEXT_RE = re.compile(
    r"\b(bank|banking|card|cards|deposit|deposits|checking|savings|account|"
    r"accounts|bonus|signup|sign[- ]?up|open|referral|referrals|app|cashback|"
    r"rewards|brokerage|invest|investing|bet|sportsbook|crypto|exchange|"
    r"trading|wallet|payout|withdraw|withdrawal|ach|direct deposit|fdic|"
    r"\$\s*\d|\d+\s*\$|dollars?)\b",
    re.IGNORECASE,
)


# Recognised "[tag]" prefix patterns at the start of a Reddit title.
_TITLE_TAG_PREFIX_RE = re.compile(r"^\s*(?:\[[^\]]{1,40}\]\s*){1,4}")
_TITLE_PAREN_PREFIX_RE = re.compile(r"^\s*\([^\)]{1,40}\)\s*")
_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF]")
_MULTI_SPACE_RE = re.compile(r"\s+")
_REPEAT_PUNCT_RE = re.compile(r"([!?.,])\1{2,}")


# ----------------------------------------------------------------------
# Public helpers
# ----------------------------------------------------------------------


def normalize_text_blob(title: str, body: str) -> str:
    return f"{title}\n{body or ''}".strip()


def clean_post_title(title: str, *, max_chars: int = 140) -> str:
    """Strip leading [tag] / (tag) prefixes, zero-width chars, repeated
    punctuation, and collapse whitespace. Keep original casing for display.
    """
    if not title:
        return ""
    t = html.unescape(title)
    t = _ZERO_WIDTH_RE.sub("", t)
    # Strip up to a couple of "[tag]" and "(tag)" prefixes.
    for _ in range(3):
        new = _TITLE_TAG_PREFIX_RE.sub("", t)
        new = _TITLE_PAREN_PREFIX_RE.sub("", new)
        if new == t:
            break
        t = new
    t = _REPEAT_PUNCT_RE.sub(r"\1", t)
    t = _MULTI_SPACE_RE.sub(" ", t).strip(" -–—•:|·")
    if len(t) > max_chars:
        cut = t[:max_chars].rsplit(" ", 1)[0]
        t = (cut + "…") if cut else t[:max_chars] + "…"
    return t


def _domain_brand(domains: list[str]) -> str | None:
    """Return the first brand whose domain matches a known mapping."""
    for d in domains:
        host = (d or "").lower().lstrip(".")
        if not host:
            continue
        if host in _BRAND_DOMAIN_MAP:
            return _BRAND_DOMAIN_MAP[host]
        # Match by suffix (handles subdomains).
        for known, slug in _BRAND_DOMAIN_MAP.items():
            if host.endswith("." + known):
                return slug
    return None


def _word_boundary_find(needle: str, hay_lower: str) -> int:
    pat = r"\b" + re.escape(needle.lower()) + r"\b"
    m = re.search(pat, hay_lower)
    return m.start() if m else -1


def _unambiguous_match(text_lower: str) -> str | None:
    # Longer aliases first to avoid "ally" winning over "ally bank".
    for alias, slug in sorted(_UNAMBIGUOUS_BRANDS.items(), key=lambda x: -len(x[0])):
        if _word_boundary_find(alias, text_lower) >= 0:
            return slug
    return None


def _ambiguous_capitalized_match(title_orig: str) -> str | None:
    """Match ambiguous brand words only when capitalized in the original
    title text. ``current revenue`` → no match; ``Open a Current account`` →
    CURRENT.
    """
    if not title_orig:
        return None
    title_lower = title_orig.lower()
    for alias, slug in sorted(_AMBIGUOUS_BRANDS.items(), key=lambda x: -len(x[0])):
        pos = _word_boundary_find(alias, title_lower)
        if pos < 0:
            continue
        # Capitalization check on the original casing.
        if pos < len(title_orig) and title_orig[pos].isupper():
            return slug
    return None


def _fallback_brand_from_title(title_clean: str) -> str:
    """Pick first 1–3 capitalized tokens that aren't stopwords.

    Returns ``UNKNOWN_BRAND`` unless the title also contains some financial
    signal — this prevents random capitalized words from off-topic posts
    (e.g. "Delaware C-Corp" in a CPA question) from being labelled as
    brands.
    """
    if not title_clean:
        return "UNKNOWN_BRAND"
    if not _FIN_CONTEXT_RE.search(title_clean):
        return "UNKNOWN_BRAND"
    # Capture sequences of capitalized words (Title Case proper nouns).
    pat = re.compile(r"\b([A-Z][A-Za-z0-9&]+(?:\s+[A-Z][A-Za-z0-9&]+){0,2})\b")
    for m in pat.finditer(title_clean):
        phrase = m.group(1).strip()
        words = phrase.split()
        # Drop the phrase if every word is a stopword.
        non_stop = [w for w in words if w.lower() not in _FALLBACK_STOPWORDS]
        if not non_stop:
            continue
        # Skip ALL CAPS shouting that's clearly not a brand (e.g. "OFFER").
        if all(w.isupper() and len(w) >= 3 for w in words):
            continue
        cleaned = " ".join(non_stop)
        if len(cleaned) < 2:
            continue
        return re.sub(r"\s+", "_", cleaned.upper())
    return "UNKNOWN_BRAND"


def pick_brand(title: str, body: str = "", domains: list[str] | None = None) -> str:
    """Identify the brand slug for an offer using the multi-stage rules in
    the module docstring."""
    title_clean = clean_post_title(title or "")
    body_clean = (body or "").strip()

    # 1) Domain wins.
    slug = _domain_brand(list(domains or []))
    if slug:
        return slug

    # 2) Title — unambiguous brands first.
    slug = _unambiguous_match((title or "").lower())
    if slug:
        return slug

    # 3) Body — unambiguous brands.
    slug = _unambiguous_match(body_clean.lower())
    if slug:
        return slug

    # 4) Title — ambiguous brands, but only when capitalized.
    slug = _ambiguous_capitalized_match(title or "")
    if slug:
        return slug

    # 5) Cleaned-title fallback (capitalized noun-phrase).
    return _fallback_brand_from_title(title_clean)


def guess_company_slug(text: str) -> str:
    """Legacy single-string entry point.

    Treats the first line as the title and the remainder as body. Modern
    callers should prefer :func:`pick_brand` and pass `domains`.
    """
    if not text:
        return "UNKNOWN_BRAND"
    parts = text.split("\n", 1)
    title = parts[0]
    body = parts[1] if len(parts) > 1 else ""
    return pick_brand(title, body, [])


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


def brand_display_name(slug: str) -> str:
    """Turn a brand slug (e.g. ``CAPITAL_ONE``) into a display string."""
    if not slug or slug == "UNKNOWN_BRAND":
        return ""
    # Special cases for human readability.
    fixups = {
        "CASH_APP": "Cash App",
        "CAPITAL_ONE": "Capital One",
        "WELLS_FARGO": "Wells Fargo",
        "ALLY_BANK": "Ally Bank",
        "US_BANK": "US Bank",
        "M1_FINANCE": "M1 Finance",
        "CRYPTO_COM": "Crypto.com",
        "ONEPAY": "OnePay",
        "BYBIT": "Bybit",
        "SOFI": "SoFi",
        "BETMGM": "BetMGM",
        "DRAFTKINGS": "DraftKings",
        "FANDUEL": "FanDuel",
        "MONEYLION": "MoneyLion",
        "KEYBANK": "KeyBank",
        "SIMPLII": "Simplii",
        "INBOXDOLLARS": "InboxDollars",
        "BINANCE": "Binance",
        "REVOLUT": "Revolut",
        "WEBULL": "Webull",
        "WEALTHFRONT": "Wealthfront",
        "ROBINHOOD": "Robinhood",
        "COINBASE": "Coinbase",
    }
    if slug in fixups:
        return fixups[slug]
    return slug.replace("_", " ").title()
