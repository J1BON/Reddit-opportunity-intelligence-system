"""Adaptive API pressure heuristic + deferred subreddit recovery queue."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reddit_intel.database import Database

PRESSURE_DECAY_EACH_CYCLE = 0.91
PRESSURE_SPIKE_ON_LIMIT = 38.0
KEY_API_PRESSURE = "api_pressure_score"


class RedditThrottle:
    """Infer pressure from 429/limit events — Reddit does not expose quota counters."""

    def __init__(self) -> None:
        self._local_pressure = 0.0

    def load_from_db(self, db: Database) -> None:
        self._local_pressure = db.get_intel_float(KEY_API_PRESSURE, 0.0)

    def persist(self, db: Database) -> None:
        db.set_intel_float(KEY_API_PRESSURE, self._local_pressure, time.time())

    @property
    def api_pressure_score(self) -> float:
        return max(0.0, min(100.0, self._local_pressure))

    def decay_tick_at_cycle_start(self) -> None:
        """Soft decay so recovered scans resume after cooldown."""
        self._local_pressure *= PRESSURE_DECAY_EACH_CYCLE

    def record_rate_limited(self) -> None:
        self._local_pressure = min(100.0, self._local_pressure + PRESSURE_SPIKE_ON_LIMIT)

    def should_reduce_comment_scanning(self) -> bool:
        return self._local_pressure >= 68.0

    def force_skip_comments_entirely(self) -> bool:
        """Heavy pressure — skip comment trees entirely this cycle."""
        return self._local_pressure >= 86.0

    def deferral_fraction(self) -> float:
        """Defer lowest-ranked fraction of subs to recovery queue."""
        p = self._local_pressure
        if p < 48:
            return 0.0
        if p < 62:
            return 0.18
        if p < 76:
            return 0.32
        return 0.48

    def sleep_backoff_seconds(self) -> float:
        p = self._local_pressure
        if p < 38:
            return 0.0
        if p < 58:
            return 0.4
        if p < 74:
            return 0.85
        return 1.6


_global_throttle = RedditThrottle()


def get_throttle() -> RedditThrottle:
    return _global_throttle
