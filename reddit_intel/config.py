"""Priority subs, keywords, brand boosts — mirrors operational spec."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

HIGH_PRIORITY_SUBREDDITS = frozenset(
    {
        "beercash",
        "beermoney",
        "beermoneyglobal",
        "BuildCapital",
        "cash4signups",
        "CryptoReferrals",
        "EarnMoneyHub",
        "easymoneyUSA",
        "promocode",
        "PromoCodeShare",
        "ReferalCodes",
        "ReferalLinks",
        "Referral",
        "referralcodes",
        "referralforpay",
        "ReferralLink",
        "Referrallinks",
        "ReferralLinks4",
        "ReferralLinksNation",
        "ReferralLinksShare",
        "ReferralNotReferal",
        "ReferralsCity",
        "ReferralTrains",
        "Referring",
        "refferalsfordummies",
        "sidehustle",
        "signupsforpay",
        "UseMyReferral",
    }
)

MEDIUM_PRIORITY_SUBREDDITS: frozenset[str] = frozenset()

EXCLUDED_SUBREDDITS = frozenset(
    {
        "AndroidAppTesters",
        "Collaboration",
        "Entrepreneur",
        "FreeCash",
        "androidapps",
        "gambling",
        "hireforgigs",
        "remoteworking",
        "sportsbook",
        "startups",
    }
)

MONITORED_SUBREDDITS = sorted(
    (HIGH_PRIORITY_SUBREDDITS | MEDIUM_PRIORITY_SUBREDDITS) - EXCLUDED_SUBREDDITS
)

KEYWORD_PHRASES = [
    "signup bonus",
    "referral",
    "invite code",
    "promo code",
    "free $",
    "earn $",
    "bank bonus",
    "direct deposit bonus",
    "sportsbook bonus",
    "free bet",
    "free stock",
    "crypto signup",
    "no deposit",
    "instant withdrawal",
    "cashback",
    "brokerage reward",
    "referral train",
    "payout proof",
    "welcome bonus",
    "deposit match",
    "cash advance app",
    "betting promo",
    "checking bonus",
    "savings bonus",
    "debit card reward",
    "ach bonus",
    "paid instantly",
]

USA_BOOST_TERMS = frozenset(
    {
        "us only",
        "usa only",
        "united states",
        "ssn",
        "direct deposit",
        "ach",
        "fdic",
        "kyc",
        "plaid",
        "cash app",
        "chime",
        "sofi",
        "webull",
        "robinhood",
        "coinbase",
        "draftkings",
        "fanduel",
        "betmgm",
        "discover",
        "capital one",
        "chase",
        "wells fargo",
        "current",
        "upgrade",
        "acorns",
        "stash",
        "irs",
        "brokerage",
        "checking account",
        "savings account",
    }
)

USA_PENALTY_TERMS = frozenset(
    {
        "non-us",
        "non us",
        "international only",
        "uk only",
        "canada only",
        "eu only",
        "outside us",
        "worldwide except",
    }
)

PAYOUT_CONFIRMATION_PHRASES = [
    "worked for me",
    "got paid",
    "received bonus",
    "withdraw successful",
    "withdrawal successful",
    "confirmed payout",
    "instant withdrawal",
    "payment proof",
    "payout proof",
    "credited",
    "bonus posted",
    "received the",
    "money hit",
]

URGENCY_PHRASES = [
    "limited time",
    "expires tonight",
    "first 100",
    "temporary bonus",
    "ending today",
    "early access",
    "boosted payout",
    "increased referral",
    "ends soon",
    "deadline",
]

SCAM_SIGNAL_PHRASES = [
    "send btc first",
    "telegram only",
    "whatsapp me",
    "investment group",
    "guaranteed returns",
    "double your money",
    "mining pool deposit",
]

SCAM_DOMAINS_HINTS = ["bit.ly/", "tinyurl.com/", "t.me/", "telegram.me/"]

# Known major brands (slug form) — entities NOT in this set + UNKNOWN_BRAND flow get unknown-intel treatment.
KNOWN_BRAND_SLUGS = frozenset(
    {
        "SOFI",
        "CHIME",
        "WEBULL",
        "ROBINHOOD",
        "COINBASE",
        "DRAFTKINGS",
        "FANDUEL",
        "BETMGM",
        "CAPITAL_ONE",
        "CHASE",
        "WELLS_FARGO",
        "DISCOVER",
        "CASH_APP",
        "CURRENT",
        "UPGRADE",
        "ACORNS",
        "STASH",
    }
)

# New app / soft launch / early discovery language — boosts first_mover_score.
EARLY_SIGNAL_PHRASES = [
    "new app",
    "just launched",
    "early access",
    "new platform",
    "fresh promo",
    "launch bonus",
    "found this today",
    "underrated",
    "not many people know",
    "invite only",
    "invite-only",
    "soft launch",
    "beta",
    "brand new",
    "new startup",
    "new fintech",
    "new sportsbook",
    "new exchange",
    "new site",
    "prelaunch",
    "pre-launch",
]

USA_ONLY_STRICT = os.getenv("USA_ONLY_STRICT", "1").strip().lower() in ("1", "true", "yes", "on")

BACKFILL_INTERVAL_SECONDS = int(os.getenv("BACKFILL_INTERVAL_SECONDS", "300"))
REPORT_INTERVAL_SECONDS = int(os.getenv("REPORT_INTERVAL_SECONDS", str(12 * 3600)))
POSTS_PER_SUB_FETCH = int(os.getenv("POSTS_PER_SUB_FETCH", "50"))
ALERT_MIN_PAYOUT_USD = float(os.getenv("ALERT_MIN_PAYOUT_USD", "20"))
ALERT_MIN_OPPORTUNITY_SCORE = float(os.getenv("ALERT_MIN_OPPORTUNITY_SCORE", "75"))

# Early gem (unknown / first-seen domain) alerts — no minimum payout (reward can be blank/$0 in text).
EARLY_GEM_FIRST_MOVER_MIN = float(os.getenv("EARLY_GEM_FIRST_MOVER_MIN", "80"))
EARLY_GEM_MAX_SATURATION = float(os.getenv("EARLY_GEM_MAX_SATURATION", "48"))
EARLY_GEM_MAX_MENTIONS = int(os.getenv("EARLY_GEM_MAX_MENTIONS", "12"))
EARLY_GEM_MIN_TRUST = float(os.getenv("EARLY_GEM_MIN_TRUST", "38"))
EARLY_GEM_MAX_SCAM_PROB = float(os.getenv("EARLY_GEM_MAX_SCAM_PROB", "48"))

# Performance: set FETCH_COMMENT_SAMPLES=0 to skip Reddit comment trees (much faster; weaker payout-confirmation signal).
_FETCH_COMMENT_ENV = os.getenv("FETCH_COMMENT_SAMPLES", "1").strip().lower()
FETCH_COMMENT_SAMPLES = _FETCH_COMMENT_ENV in ("1", "true", "yes", "on")
COMMENT_SAMPLE_LIMIT = max(1, min(200, int(os.getenv("COMMENT_SAMPLE_LIMIT", "40"))))

# HEAD probe on first HTTPS referral link (extra latency). 0/false by default.
CHECK_URL_INTEGRITY = os.getenv("CHECK_URL_INTEGRITY", "0").strip().lower() in ("1", "true", "yes", "on")

# ----------------------------------------------------------------------
# Site-wide discovery (Reddit-wide search beyond our monitored sub list)
# ----------------------------------------------------------------------

DISCOVERY_ENABLED = os.getenv("DISCOVERY_ENABLED", "1").strip().lower() in (
    "1", "true", "yes", "on",
)
DISCOVERY_QUERIES_PER_TICK = max(1, int(os.getenv("DISCOVERY_QUERIES_PER_TICK", "5")))
DISCOVERY_RESULTS_PER_QUERY = max(1, min(100, int(os.getenv("DISCOVERY_RESULTS_PER_QUERY", "25"))))
DISCOVERY_TIME_FILTER = os.getenv("DISCOVERY_TIME_FILTER", "hour").strip().lower()

# Each query is a high-signal phrase from the money-making vocabulary.
# We rotate through these across cron ticks so every query gets exercised
# at least once per ~hour even at the 10-min cadence.
DISCOVERY_QUERIES: tuple[str, ...] = (
    "signup bonus",
    "referral code",
    "promo code",
    "invite code",
    "free $20",
    "free $50",
    "free $100",
    "free $200",
    "earn $",
    "welcome bonus",
    "deposit bonus",
    "deposit match",
    "checking bonus",
    "savings bonus",
    "ach bonus",
    "direct deposit bonus",
    "no deposit bonus",
    "free stock",
    "free crypto",
    "free bitcoin",
    "instant withdrawal",
    "cash bonus",
    "$25 bonus",
    "$50 bonus",
    "$100 bonus",
    "$200 bonus",
    "bank bonus",
    "brokerage bonus",
    "fintech referral",
    "launch bonus",
    "early access bonus",
    "new app pays",
    "app sign up bonus",
    "referral train",
    "boosted referral",
    "limited time promo",
)

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME", "")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "USAOpportunityIntelBot/1.0")
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")
# Discord Bot token + channel: alerts POST via Discord REST (no separate discord.py process).
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_ALERT_CHANNEL_ID = os.getenv("DISCORD_ALERT_CHANNEL_ID", "").strip()
