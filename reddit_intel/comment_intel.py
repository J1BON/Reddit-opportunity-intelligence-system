"""Weighted comment scan: confirmations vs complaints vs repetitive spam."""

from __future__ import annotations

import hashlib
import math
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import praw

from reddit_intel.detectors import payout_confirmation_hits
from reddit_intel.intelligence_signals import (
    NEGATIVE_PAYOUT_PHRASES,
    WITHDRAWAL_FRICTION_PHRASES,
)


def _norm_body(body: str) -> str:
    return re.sub(r"\s+", " ", (body or "").lower().strip())[:240]


def _comment_credibility_weight(author: object | None) -> float:
    """Older / higher-karma commenters count slightly more."""
    if author is None:
        return 0.65
    try:
        lk = float(getattr(author, "link_karma", 0) or 0)
        ck = float(getattr(author, "comment_karma", 0) or 0)
        created = float(getattr(author, "created_utc", 0) or 0)
    except (TypeError, ValueError):
        return 0.65
    age_days = max(30.0, (time.time() - created) / 86400.0) if created else 90.0
    karma = lk + ck
    w = 0.55 + min(1.25, math.log1p(karma) / 10.0) + min(0.45, math.log1p(max(1.0, age_days)) / 25.0)
    return max(0.35, min(2.2, w))


@dataclass
class CommentIntelResult:
    comments_sampled: int
    payout_confirmation_lines: int
    weighted_positive_sum: float
    repetitive_confirmation_penalty: float
    negative_lines: int
    withdrawal_lines: int


def scan_submission_comments(
    submission: "praw.models.Submission",
    limit: int,
) -> CommentIntelResult:
    sampled = 0
    confirms = 0
    w_pos = 0.0
    neg_lines = 0
    wd_lines = 0
    body_hashes: dict[str, int] = {}

    try:
        submission.comments.replace_more(limit=0)
    except Exception:
        pass

    try:
        for c in submission.comments.list():
            if sampled >= limit:
                break
            body = getattr(c, "body", None)
            if not body:
                continue
            sampled += 1
            low = body.lower()

            if payout_confirmation_hits(body):
                confirms += 1
                w = _comment_credibility_weight(getattr(c, "author", None))
                w_pos += w
                h = hashlib.md5(_norm_body(body).encode(), usedforsecurity=False).hexdigest()[:12]
                body_hashes[h] = body_hashes.get(h, 0) + 1

            if any(p in low for p in NEGATIVE_PAYOUT_PHRASES):
                neg_lines += 1
            if any(p in low for p in WITHDRAWAL_FRICTION_PHRASES):
                wd_lines += 1
    except Exception:
        pass

    repetitive_penalty = 0.0
    for _h, cnt in body_hashes.items():
        if cnt >= 3:
            repetitive_penalty += (cnt - 2) * 0.35

    return CommentIntelResult(
        comments_sampled=sampled,
        payout_confirmation_lines=confirms,
        weighted_positive_sum=w_pos,
        repetitive_confirmation_penalty=repetitive_penalty,
        negative_lines=neg_lines,
        withdrawal_lines=wd_lines,
    )
