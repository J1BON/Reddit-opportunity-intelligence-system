"""Site-wide Reddit discovery — find offer posts outside our monitored subs.

Rather than only polling a hardcoded list of subreddits, we periodically run
search queries against *all of Reddit* (`/search.json`) for high-signal
phrases like "signup bonus", "referral code", "free $20", "launch bonus"
etc. Hits are funneled through the same `process_submission()` pipeline as
direct sub scans, so every offer-shaped post on Reddit eventually flows
through the same dedupe / scoring / alerting machinery.

To stay under the ~10 req/min public-Reddit rate budget, we rotate through
the query list across cron ticks: each tick fires a small shard of queries
deterministic from the wall clock. With 30 queries / 5 per tick at the
10-min cadence, every query is exercised at least every 60 minutes.

Subreddits whose posts repeatedly produce useful hits are recorded in the
``discovered_subreddits`` table so we can see what new corners of Reddit
the bot is reaching, and (optionally) promote them to full monitored
status in a future tick.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import praw

from reddit_intel.config import (
    DISCOVERY_ENABLED,
    DISCOVERY_QUERIES,
    DISCOVERY_QUERIES_PER_TICK,
    DISCOVERY_RESULTS_PER_QUERY,
    DISCOVERY_TIME_FILTER,
    EXCLUDED_SUBREDDITS,
)
from reddit_intel.database import Database
from reddit_intel.throttle import get_throttle


def _select_queries_for_tick(now: float | None = None) -> list[str]:
    """Pick a deterministic rotating shard of queries for this tick.

    Uses `int(now // 600)` as the tick counter so consecutive cron ticks
    each fire a fresh slice and every query gets exercised over time.
    """
    if not DISCOVERY_QUERIES:
        return []
    n_per_tick = max(1, int(DISCOVERY_QUERIES_PER_TICK))
    total = len(DISCOVERY_QUERIES)
    tick = int((now if now is not None else time.time()) // 600)
    start = (tick * n_per_tick) % total
    picked: list[str] = []
    for i in range(min(n_per_tick, total)):
        picked.append(DISCOVERY_QUERIES[(start + i) % total])
    return picked


def _iter_search_results(reddit: Any, query: str, limit: int) -> list[Any]:
    """Run a search through whichever reddit client is in use.

    The no-auth `PublicReddit` exposes ``search_all``; PRAW exposes the
    same surface as ``reddit.subreddit("all").search(...)``.
    """
    try:
        if hasattr(reddit, "search_all"):
            return list(
                reddit.search_all(
                    query,
                    sort="new",
                    t=DISCOVERY_TIME_FILTER,
                    limit=limit,
                )
            )
        # PRAW path.
        return list(
            reddit.subreddit("all").search(
                query,
                sort="new",
                time_filter=DISCOVERY_TIME_FILTER,
                limit=limit,
            )
        )
    except Exception as ex:  # noqa: BLE001 — propagated as 0 results
        low = str(ex).lower()
        if (
            "429" in low
            or "too many" in low
            or "ratelimit" in low
            or "TooManyRequests" in type(ex).__name__
        ):
            th = get_throttle()
            th.record_rate_limited()
        print(f"[discovery] query={query!r} error: {ex}", flush=True)
        return []


def run_discovery_cycle(reddit: Any, db: Database) -> dict[str, int]:
    """Run one tick's worth of site-wide discovery searches.

    Returns a small stats dict so the caller can log how many candidates we
    surfaced this tick.
    """
    if not DISCOVERY_ENABLED:
        return {"queries": 0, "candidates": 0, "ingested": 0}

    # Import lazily to avoid a circular dependency:
    # engine imports discovery, discovery uses process_submission.
    from reddit_intel.engine import process_submission

    queries = _select_queries_for_tick()
    th = get_throttle()
    excluded = {s.lower() for s in EXCLUDED_SUBREDDITS}

    candidates = 0
    ingested = 0
    new_subs: dict[str, int] = {}

    for q in queries:
        time.sleep(th.sleep_backoff_seconds())
        results = _iter_search_results(reddit, q, DISCOVERY_RESULTS_PER_QUERY)
        candidates += len(results)
        for sub in results:
            sub_name = ""
            try:
                sub_name = str(getattr(sub, "subreddit", "")).lower()
            except Exception:
                pass
            if sub_name in excluded:
                continue
            try:
                # Discovery results are noisy and we want low per-post latency
                # (we've already burnt a /search.json request per query, so
                # be miserly with comment fetches).
                cid = process_submission(sub, db, fetch_comments=False)
            except Exception as ex:  # noqa: BLE001
                low = str(ex).lower()
                if (
                    "429" in low
                    or "too many" in low
                    or "ratelimit" in low
                    or "TooManyRequests" in type(ex).__name__
                ):
                    th.record_rate_limited()
                    break
                continue
            if cid:
                ingested += 1
                if sub_name:
                    new_subs[sub_name] = new_subs.get(sub_name, 0) + 1

    if new_subs:
        try:
            db.record_discovered_subreddits(new_subs)
        except Exception as ex:  # noqa: BLE001
            print(f"[discovery] failed to persist discovered subs: {ex}", flush=True)

    print(
        f"[discovery] queries={len(queries)} candidates={candidates} "
        f"ingested={ingested} new_subs={len(new_subs)}",
        flush=True,
    )
    return {"queries": len(queries), "candidates": candidates, "ingested": ingested}
