"""No-credential Reddit client using public ``.json`` endpoints.

Drop-in subset of ``praw.Reddit`` for the engine's actual usage surface:

    reddit.subreddit(name).new(limit=N)            -> iterator of submissions
    submission.title / .selftext / .url / ...      -> standard fields
    submission.comments.replace_more(limit=0)      -> no-op
    submission.comments.list()                     -> flat list of comment objects

Reddit allows unauthenticated access to ``https://www.reddit.com/<path>.json``
endpoints, but at much lower rate limits than authenticated OAuth (roughly
~10 requests/minute shared per IP). This client throttles every HTTP request
and backs off on HTTP 429.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import Any


class _Author:
    """Stand-in for praw's redditor object — we only have the username from a
    post/comment listing. Karma and account age default to neutral values so
    credibility heuristics still work (just at lower confidence)."""

    __slots__ = ("name", "link_karma", "comment_karma", "created_utc")

    def __init__(self, name: str | None) -> None:
        self.name = name or ""
        self.link_karma = 0
        self.comment_karma = 0
        self.created_utc = 0.0

    def __str__(self) -> str:
        return self.name

    def __bool__(self) -> bool:
        return bool(self.name)


class _Comment:
    __slots__ = ("id", "body", "author", "score", "created_utc")

    def __init__(self, data: dict[str, Any]) -> None:
        self.id = data.get("id", "") or ""
        self.body = data.get("body", "") or ""
        author_name = data.get("author")
        deleted = author_name in (None, "", "[deleted]", "[removed]")
        self.author = None if deleted else _Author(str(author_name))
        self.score = int(data.get("score") or 0)
        try:
            self.created_utc = float(data.get("created_utc") or 0)
        except (TypeError, ValueError):
            self.created_utc = 0.0


class _Comments:
    """Flattened comment forest. Mirrors the two PRAW methods the engine
    actually calls: ``replace_more(limit=0)`` (no-op here) and ``list()``."""

    def __init__(self, listing: list[dict[str, Any]] | None) -> None:
        self._items: list[_Comment] = []
        if listing:
            self._flatten(listing)

    def _flatten(self, children: list[dict[str, Any]]) -> None:
        for ch in children:
            kind = ch.get("kind")
            data = ch.get("data") or {}
            if kind == "t1":
                self._items.append(_Comment(data))
                replies = data.get("replies")
                if isinstance(replies, dict):
                    nested = (replies.get("data") or {}).get("children") or []
                    self._flatten(nested)
            # "more" stubs are intentionally ignored: fetching them would cost
            # extra API calls and the engine only needs a sample anyway.

    def replace_more(self, limit: int = 0) -> None:  # noqa: ARG002
        return None

    def list(self) -> list[_Comment]:
        return self._items


class _Subreddit:
    __slots__ = ("_client", "_name")

    def __init__(self, client: PublicReddit, name: str) -> None:
        self._client = client
        self._name = name

    def __str__(self) -> str:
        return self._name

    def new(self, limit: int = 50) -> Iterator[_Submission]:
        yield from self._listing("new", limit)

    def hot(self, limit: int = 25) -> Iterator[_Submission]:
        yield from self._listing("hot", limit)

    def _listing(self, kind: str, limit: int) -> Iterator[_Submission]:
        path = f"/r/{urllib.parse.quote(self._name, safe='')}/{kind}.json"
        params = {"limit": str(int(limit)), "raw_json": "1"}
        data = self._client._get_json(path, params)
        children = ((data or {}).get("data") or {}).get("children") or []
        for ch in children:
            if ch.get("kind") == "t3":
                yield _Submission(self._client, ch.get("data") or {}, self)


class _Submission:
    """Subset of ``praw.models.Submission`` consumed by the engine."""

    def __init__(
        self,
        client: PublicReddit,
        data: dict[str, Any],
        subreddit: _Subreddit,
    ) -> None:
        self._client = client
        self.id = str(data.get("id", "") or "")
        self.name = str(data.get("name") or (f"t3_{self.id}" if self.id else ""))
        self.title = data.get("title", "") or ""
        self.selftext = data.get("selftext", "") or ""
        self.url = data.get("url", "") or ""
        self.permalink = data.get("permalink", "") or ""
        try:
            self.score = int(data.get("score") or 0)
        except (TypeError, ValueError):
            self.score = 0
        try:
            self.num_comments = int(data.get("num_comments") or 0)
        except (TypeError, ValueError):
            self.num_comments = 0
        try:
            self.created_utc = float(data.get("created_utc") or 0)
        except (TypeError, ValueError):
            self.created_utc = 0.0
        author_name = data.get("author")
        deleted = author_name in (None, "", "[deleted]", "[removed]")
        self.author = None if deleted else _Author(str(author_name))
        self.subreddit = subreddit
        self._comments_cache: _Comments | None = None

    @property
    def comments(self) -> _Comments:
        if self._comments_cache is None:
            self._comments_cache = self._fetch_comments()
        return self._comments_cache

    def _fetch_comments(self) -> _Comments:
        if not self.id:
            return _Comments([])
        path = f"/comments/{urllib.parse.quote(self.id, safe='')}.json"
        params = {"raw_json": "1", "limit": "200", "depth": "4"}
        try:
            data = self._client._get_json(path, params)
        except Exception:
            return _Comments([])
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], dict):
            children = (data[1].get("data") or {}).get("children") or []
            return _Comments(children)
        return _Comments([])


class PublicReddit:
    """Tiny PRAW-compatible client that hits Reddit's public JSON endpoints.

    No OAuth, no app registration, no username/password. The trade-off is a
    much tighter shared rate limit (~10 req/min unauthenticated). We sleep
    ``min_interval_s`` seconds between calls and back off on 429s.
    """

    BASE = "https://www.reddit.com"

    def __init__(
        self,
        user_agent: str,
        min_interval_s: float = 4.0,
        timeout_s: float = 20.0,
    ) -> None:
        ua = (user_agent or "").strip()
        if not ua:
            ua = "USAOpportunityIntelBot/1.0 (no-auth public mode)"
        self._ua = ua
        self._min_interval = max(0.5, float(min_interval_s))
        self._timeout = float(timeout_s)
        self._last_call = 0.0

    def subreddit(self, name: str) -> _Subreddit:
        return _Subreddit(self, name)

    def search_all(
        self,
        query: str,
        sort: str = "new",
        t: str = "hour",
        limit: int = 25,
    ) -> Iterator[_Submission]:
        """Site-wide Reddit search via the public ``/search.json`` endpoint.

        Each result is wrapped as a ``_Submission`` with a freshly constructed
        ``_Subreddit`` derived from the result's own ``data["subreddit"]``,
        so downstream code (`str(sub.subreddit)`) keeps working.
        """
        params = {
            "q": query,
            "sort": sort,
            "t": t,
            "limit": str(int(limit)),
            # Must be false for site-wide search; empty string is treated as
            # ambiguous and Reddit often returns an empty listing.
            "restrict_sr": "false",
            "include_over_18": "on",
            "raw_json": "1",
        }
        path = "/search.json"
        data = self._get_json(path, params)
        children = ((data or {}).get("data") or {}).get("children") or []
        for ch in children:
            if ch.get("kind") != "t3":
                continue
            d = ch.get("data") or {}
            sub_name = str(d.get("subreddit") or "")
            sub = _Subreddit(self, sub_name)
            yield _Submission(self, d, sub)

    def _throttle(self) -> None:
        gap = time.time() - self._last_call
        if gap < self._min_interval:
            time.sleep(self._min_interval - gap)
        self._last_call = time.time()

    def _get_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = self.BASE + path
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        last_err: Exception | None = None
        for attempt in range(3):
            self._throttle()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self._ua,
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as r:
                    body = r.read().decode("utf-8", errors="replace")
                    return json.loads(body)
            except urllib.error.HTTPError as ex:
                last_err = ex
                if ex.code == 429:
                    # Honour Retry-After when present, otherwise exponential.
                    try:
                        retry_after = float(ex.headers.get("Retry-After", "")) if ex.headers else 0
                    except (TypeError, ValueError):
                        retry_after = 0
                    sleep_s = max(retry_after, 6.0 * (attempt + 1))
                    time.sleep(min(sleep_s, 45.0))
                    if attempt == 2:
                        # Re-raise as a recognisable rate-limit error so the
                        # engine's exception handler defers this subreddit.
                        raise RuntimeError(
                            "429 too many requests (public Reddit JSON rate limit)"
                        ) from ex
                    continue
                if 500 <= ex.code < 600:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise
            except urllib.error.URLError as ex:
                last_err = ex
                time.sleep(1.5 * (attempt + 1))
                continue
            except json.JSONDecodeError as ex:
                last_err = ex
                time.sleep(1.0)
                continue

        if last_err is not None:
            raise last_err
        raise RuntimeError(f"Failed to fetch {url}")
