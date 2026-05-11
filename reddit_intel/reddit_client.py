"""Reddit client factory.

Two modes:

1. **OAuth (PRAW)** — preferred. Requires a "script" app + username/password
   (see ``.env.example``). Higher rate limits, full PRAW feature set.

2. **Public JSON (no auth)** — fallback for when you can't get API credentials.
   Uses Reddit's public ``.json`` endpoints. Heavily rate-limited (~10 req/min
   shared per IP), but needs zero registration.

Selection rules:

- ``REDDIT_NO_AUTH=1`` (env) -> always use the public client.
- All four OAuth env vars present -> use PRAW.
- Otherwise -> warn on stderr and fall back to the public client.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from reddit_intel.config import (
    REDDIT_CLIENT_ID,
    REDDIT_CLIENT_SECRET,
    REDDIT_PASSWORD,
    REDDIT_PUBLIC_MIN_INTERVAL_S,
    REDDIT_PUBLIC_TIMEOUT_S,
    REDDIT_USER_AGENT,
    REDDIT_USERNAME,
)
from reddit_intel.public_client import PublicReddit


def _force_no_auth() -> bool:
    return os.getenv("REDDIT_NO_AUTH", "").strip().lower() in ("1", "true", "yes", "on")


def _have_oauth_creds() -> bool:
    return all(
        [REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME, REDDIT_PASSWORD]
    )


def make_reddit() -> Any:
    """Return either a ``praw.Reddit`` or a PRAW-compatible ``PublicReddit``."""

    if _force_no_auth():
        print(
            "[reddit] REDDIT_NO_AUTH=1 — using public JSON endpoints (no OAuth, "
            "rate-limited).",
            file=sys.stderr,
        )
        return PublicReddit(
            user_agent=REDDIT_USER_AGENT,
            min_interval_s=REDDIT_PUBLIC_MIN_INTERVAL_S,
            timeout_s=REDDIT_PUBLIC_TIMEOUT_S,
        )

    if _have_oauth_creds():
        try:
            import praw
        except ImportError as ex:
            print(
                "[reddit] OAuth credentials are set but `praw` is not installed. "
                "Run `pip install -r requirements.txt`, or unset the four "
                "REDDIT_* credentials to use the no-auth public client.",
                file=sys.stderr,
            )
            raise RuntimeError("praw not installed") from ex
        return praw.Reddit(
            client_id=REDDIT_CLIENT_ID,
            client_secret=REDDIT_CLIENT_SECRET,
            username=REDDIT_USERNAME,
            password=REDDIT_PASSWORD,
            user_agent=REDDIT_USER_AGENT,
        )

    missing = [
        n
        for n, v in [
            ("REDDIT_CLIENT_ID", REDDIT_CLIENT_ID),
            ("REDDIT_CLIENT_SECRET", REDDIT_CLIENT_SECRET),
            ("REDDIT_USERNAME", REDDIT_USERNAME),
            ("REDDIT_PASSWORD", REDDIT_PASSWORD),
        ]
        if not v
    ]
    print(
        "[reddit] No OAuth credentials ("
        + ", ".join(missing)
        + "). Falling back to public JSON endpoints (no auth, ~10 req/min limit). "
        "Set REDDIT_NO_AUTH=0 and fill .env to enable PRAW.",
        file=sys.stderr,
    )
    return PublicReddit(
        user_agent=REDDIT_USER_AGENT,
        min_interval_s=REDDIT_PUBLIC_MIN_INTERVAL_S,
        timeout_s=REDDIT_PUBLIC_TIMEOUT_S,
    )
