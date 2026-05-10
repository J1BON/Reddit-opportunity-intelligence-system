"""SQLite persistence: raw posts, comments, canonical offers, alerts."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from reddit_intel.config import HIGH_PRIORITY_SUBREDDITS, MEDIUM_PRIORITY_SUBREDDITS

_DB_LOCK = threading.Lock()


def default_db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "reddit_intel.db"


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns/tables for existing DBs created before entity-intel upgrades."""
    cur = conn.execute("PRAGMA table_info(canonical_offers)")
    offer_cols = {row[1] for row in cur.fetchall()}
    for col, typ in (
        ("first_mover_score", "REAL DEFAULT 0"),
        ("predicted_growth_score", "REAL DEFAULT 0"),
        ("saturation_risk", "REAL DEFAULT 0"),
        ("estimated_profit_window", "TEXT DEFAULT ''"),
        ("startup_legitimacy_score", "REAL DEFAULT 0"),
        ("is_unknown_entity", "INTEGER DEFAULT 0"),
        ("launch_status", "TEXT DEFAULT ''"),
        ("primary_domain", "TEXT DEFAULT ''"),
        ("engagement_acceleration_score", "REAL DEFAULT 0"),
        ("estimated_saturation_hours_remaining", "REAL DEFAULT 0"),
        ("payout_failure_rate", "REAL DEFAULT 0"),
        ("complaint_score", "REAL DEFAULT 0"),
        ("competition_density_score", "REAL DEFAULT 0"),
        ("state_coverage_score", "REAL DEFAULT 0"),
        ("withdrawal_friction_score", "REAL DEFAULT 0"),
        ("recurring_bonus_probability", "REAL DEFAULT 0"),
        ("poster_reliability_score", "REAL DEFAULT 50"),
        ("fatigue_score", "REAL DEFAULT 0"),
        ("offer_integrity_score", "REAL DEFAULT 0"),
        ("temporary_boost_score", "REAL DEFAULT 0"),
        ("weighted_confirmation_score", "REAL DEFAULT 0"),
        ("stackability_score", "REAL DEFAULT 0"),
        ("estimated_maximized_reward", "TEXT DEFAULT ''"),
        ("decay_velocity", "REAL DEFAULT 0"),
        ("learning_trust_delta", "REAL DEFAULT 0"),
        ("learning_scam_delta", "REAL DEFAULT 0"),
        ("mentions_prior_snapshot", "INTEGER DEFAULT -1"),
        ("prior_refresh_ts", "REAL DEFAULT 0"),
        ("api_pressure_score_snapshot", "REAL DEFAULT 0"),
        ("deferred_queue_depth_snapshot", "INTEGER DEFAULT 0"),
        ("post_title", "TEXT DEFAULT ''"),
        ("post_title_clean", "TEXT DEFAULT ''"),
    ):
        if col not in offer_cols:
            conn.execute(f"ALTER TABLE canonical_offers ADD COLUMN {col} {typ}")

    cur = conn.execute("PRAGMA table_info(alerts_log)")
    alert_cols = {row[1] for row in cur.fetchall()}
    if "alert_kind" not in alert_cols:
        conn.execute("ALTER TABLE alerts_log ADD COLUMN alert_kind TEXT DEFAULT 'standard'")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tracked_domains (
            domain TEXT PRIMARY KEY,
            first_seen REAL NOT NULL,
            last_seen REAL NOT NULL,
            mention_count INTEGER NOT NULL DEFAULT 1,
            subreddits_json TEXT NOT NULL DEFAULT '[]',
            domain_age_estimate TEXT,
            affiliate_hint INTEGER DEFAULT 0
        );
        """
    )
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tracked_domain_posts (
            domain TEXT NOT NULL,
            reddit_post_id TEXT NOT NULL,
            seen_at REAL NOT NULL,
            PRIMARY KEY (domain, reddit_post_id)
        );

        CREATE TABLE IF NOT EXISTS intel_kv (
            k TEXT PRIMARY KEY,
            v REAL DEFAULT 0,
            v_text TEXT,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deferred_scan_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subreddit TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            queued_at REAL NOT NULL,
            reason TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_deferred_pri ON deferred_scan_queue(priority DESC, queued_at ASC);

        CREATE TABLE IF NOT EXISTS subreddit_stats (
            subreddit TEXT PRIMARY KEY,
            posts_sampled INTEGER NOT NULL DEFAULT 0,
            scam_sum REAL NOT NULL DEFAULT 0,
            confirm_weight_sum REAL NOT NULL DEFAULT 0,
            gem_sum REAL NOT NULL DEFAULT 0,
            opp_sum REAL NOT NULL DEFAULT 0,
            sat_sum REAL NOT NULL DEFAULT 0,
            complaint_sum REAL NOT NULL DEFAULT 0,
            quality_score REAL NOT NULL DEFAULT 50,
            decay_score REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS poster_stats (
            author TEXT PRIMARY KEY,
            posts INTEGER NOT NULL DEFAULT 0,
            confirm_weight REAL NOT NULL DEFAULT 0,
            complaint_events INTEGER NOT NULL DEFAULT 0,
            reliability_score REAL NOT NULL DEFAULT 50,
            updated_at REAL NOT NULL
        );
        """
    )
    conn.commit()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;

        CREATE TABLE IF NOT EXISTS raw_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reddit_id TEXT NOT NULL UNIQUE,
            subreddit TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            url TEXT,
            permalink TEXT,
            author TEXT,
            score INTEGER,
            num_comments INTEGER,
            created_utc REAL,
            fetched_at REAL NOT NULL,
            is_comment INTEGER NOT NULL DEFAULT 0,
            parent_post_reddit_id TEXT,
            raw_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_raw_posts_sub_created ON raw_posts(subreddit, created_utc);
        CREATE INDEX IF NOT EXISTS idx_raw_posts_reddit ON raw_posts(reddit_id);

        CREATE TABLE IF NOT EXISTS canonical_offers (
            canonical_offer_id TEXT PRIMARY KEY,
            company_name TEXT,
            offer_type TEXT,
            reward_amount TEXT,
            currency TEXT DEFAULT 'USD',
            deposit_required INTEGER DEFAULT 0,
            direct_deposit_required INTEGER DEFAULT 0,
            ssn_required INTEGER DEFAULT 0,
            minimum_deposit TEXT,
            withdrawal_minimum TEXT,
            requirements_json TEXT,
            eligible_states_json TEXT,
            excluded_states_json TEXT,
            payout_methods_json TEXT,
            platforms_json TEXT,
            promo_codes_json TEXT,
            referral_links_json TEXT,
            expiration_date TEXT,
            estimated_completion_time TEXT,
            difficulty_score REAL,
            risk_score REAL,
            scam_probability REAL,
            trust_score REAL,
            hidden_gem_score REAL,
            opportunity_score REAL,
            engagement_score REAL,
            saturation_score REAL,
            mentions_count INTEGER DEFAULT 0,
            confirmation_count INTEGER DEFAULT 0,
            trend_velocity TEXT,
            subreddits_json TEXT,
            source_posts_json TEXT,
            ai_summary TEXT,
            best_signup_strategy TEXT,
            trust_reasoning TEXT,
            risk_explanation TEXT,
            first_seen REAL NOT NULL,
            latest_seen REAL NOT NULL,
            urgent INTEGER DEFAULT 0,
            merged_engagement_score REAL DEFAULT 0,
            updated_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_canonical_latest ON canonical_offers(latest_seen DESC);

        CREATE TABLE IF NOT EXISTS tracked_domains (
            domain TEXT PRIMARY KEY,
            first_seen REAL NOT NULL,
            last_seen REAL NOT NULL,
            mention_count INTEGER NOT NULL DEFAULT 1,
            subreddits_json TEXT NOT NULL DEFAULT '[]',
            domain_age_estimate TEXT,
            affiliate_hint INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tracked_domain_posts (
            domain TEXT NOT NULL,
            reddit_post_id TEXT NOT NULL,
            seen_at REAL NOT NULL,
            PRIMARY KEY (domain, reddit_post_id)
        );

        CREATE TABLE IF NOT EXISTS offer_post_map (
            canonical_offer_id TEXT NOT NULL REFERENCES canonical_offers(canonical_offer_id),
            reddit_post_id TEXT NOT NULL REFERENCES raw_posts(reddit_id),
            PRIMARY KEY (canonical_offer_id, reddit_post_id)
        );

        CREATE TABLE IF NOT EXISTS alerts_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_offer_id TEXT NOT NULL,
            fired_at REAL NOT NULL,
            payload TEXT NOT NULL,
            alert_kind TEXT DEFAULT 'standard'
        );

        CREATE TABLE IF NOT EXISTS reports_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            window_start REAL NOT NULL,
            window_end REAL NOT NULL,
            markdown TEXT NOT NULL,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS intel_kv (
            k TEXT PRIMARY KEY,
            v REAL DEFAULT 0,
            v_text TEXT,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deferred_scan_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subreddit TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            queued_at REAL NOT NULL,
            reason TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_deferred_pri ON deferred_scan_queue(priority DESC, queued_at ASC);

        CREATE TABLE IF NOT EXISTS subreddit_stats (
            subreddit TEXT PRIMARY KEY,
            posts_sampled INTEGER NOT NULL DEFAULT 0,
            scam_sum REAL NOT NULL DEFAULT 0,
            confirm_weight_sum REAL NOT NULL DEFAULT 0,
            gem_sum REAL NOT NULL DEFAULT 0,
            opp_sum REAL NOT NULL DEFAULT 0,
            sat_sum REAL NOT NULL DEFAULT 0,
            complaint_sum REAL NOT NULL DEFAULT 0,
            quality_score REAL NOT NULL DEFAULT 50,
            decay_score REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS poster_stats (
            author TEXT PRIMARY KEY,
            posts INTEGER NOT NULL DEFAULT 0,
            confirm_weight REAL NOT NULL DEFAULT 0,
            complaint_events INTEGER NOT NULL DEFAULT 0,
            reliability_score REAL NOT NULL DEFAULT 50,
            updated_at REAL NOT NULL
        );
        """
    )
    _migrate(conn)


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            init_schema(c)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        with _DB_LOCK:
            conn = sqlite3.connect(str(self.path))
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

    def upsert_raw_post(self, row: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO raw_posts (
                    reddit_id, subreddit, title, body, url, permalink, author,
                    score, num_comments, created_utc, fetched_at, is_comment,
                    parent_post_reddit_id, raw_json
                ) VALUES (
                    :reddit_id, :subreddit, :title, :body, :url, :permalink, :author,
                    :score, :num_comments, :created_utc, :fetched_at, :is_comment,
                    :parent_post_reddit_id, :raw_json
                )
                ON CONFLICT(reddit_id) DO UPDATE SET
                    score = excluded.score,
                    num_comments = excluded.num_comments,
                    fetched_at = excluded.fetched_at,
                    body = COALESCE(excluded.body, raw_posts.body)
                """,
                row,
            )
            conn.commit()

    def upsert_canonical_offer(self, offer_id: str, fields: dict[str, Any]) -> None:
        with self.connect() as conn:
            cols = ", ".join(fields.keys())
            placeholders = ", ".join(f":{k}" for k in fields)
            updates = ", ".join(f"{k} = excluded.{k}" for k in fields if k != "canonical_offer_id")
            conn.execute(
                f"""
                INSERT INTO canonical_offers ({cols})
                VALUES ({placeholders})
                ON CONFLICT(canonical_offer_id) DO UPDATE SET {updates}
                """,
                fields,
            )
            conn.commit()

    def link_offer_post(self, canonical_id: str, reddit_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO offer_post_map (canonical_offer_id, reddit_post_id)
                VALUES (?, ?)
                """,
                (canonical_id, reddit_id),
            )
            conn.commit()

    def is_offer_post_linked(self, canonical_id: str, reddit_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT 1 FROM offer_post_map
                WHERE canonical_offer_id = ? AND reddit_post_id = ?
                """,
                (canonical_id, reddit_id),
            )
            return cur.fetchone() is not None

    def log_alert(self, canonical_id: str, payload: dict[str, Any], alert_kind: str = "standard") -> None:
        import time

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alerts_log (canonical_offer_id, fired_at, payload, alert_kind)
                VALUES (?, ?, ?, ?)
                """,
                (canonical_id, time.time(), json.dumps(payload), alert_kind),
            )
            conn.commit()

    def log_report(self, window_start: float, window_end: float, markdown: str) -> None:
        import time

        with self.connect() as conn:
            conn.execute(
                "INSERT INTO reports_log (window_start, window_end, markdown, created_at) VALUES (?, ?, ?, ?)",
                (window_start, window_end, markdown, time.time()),
            )
            conn.commit()

    def fetch_offers_in_window(self, start_ts: float, end_ts: float) -> list[sqlite3.Row]:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM canonical_offers
                WHERE latest_seen >= ? AND latest_seen <= ?
                ORDER BY opportunity_score DESC
                """,
                (start_ts, end_ts),
            )
            return list(cur.fetchall())

    def get_canonical(self, offer_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            cur = conn.execute(
                "SELECT * FROM canonical_offers WHERE canonical_offer_id = ?",
                (offer_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def fetch_recent_canonical(self, since_ts: float) -> list[sqlite3.Row]:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT * FROM canonical_offers WHERE latest_seen >= ?
                ORDER BY opportunity_score DESC
                """,
                (since_ts,),
            )
            return list(cur.fetchall())

    def last_alert_time(self, canonical_id: str, alert_kind: str = "standard") -> float | None:
        with self.connect() as conn:
            cur = conn.execute(
                """
                SELECT MAX(fired_at) FROM alerts_log
                WHERE canonical_offer_id = ?
                  AND COALESCE(alert_kind, 'standard') = ?
                """,
                (canonical_id, alert_kind),
            )
            row = cur.fetchone()
            if row and row[0] is not None:
                return float(row[0])
            return None

    def touch_domains(
        self,
        domains: list[str],
        subreddit: str,
        reddit_post_id: str,
        now: float,
        domain_age_estimates: dict[str, str],
        affiliate_hints: dict[str, bool],
    ) -> dict[str, tuple[bool, int]]:
        """Upsert domain rows; counts each Reddit post at most once per domain.
        Returns domain -> (was_first_domain_row_insert, mention_count_after).
        """
        result: dict[str, tuple[bool, int]] = {}
        sub_norm = subreddit.strip()
        post_id = reddit_post_id.strip()
        with self.connect() as conn:
            for domain in domains:
                d = domain.lower().strip()
                if not d:
                    continue
                age = domain_age_estimates.get(d) or domain_age_estimates.get(domain, "")
                aff = 1 if affiliate_hints.get(d) or affiliate_hints.get(domain, False) else 0

                cur = conn.execute(
                    "SELECT 1 FROM tracked_domain_posts WHERE domain = ? AND reddit_post_id = ?",
                    (d, post_id),
                )
                new_post_for_domain = cur.fetchone() is None

                row = conn.execute(
                    "SELECT mention_count, subreddits_json FROM tracked_domains WHERE domain = ?",
                    (d,),
                ).fetchone()

                if row is None:
                    subs_json = json.dumps([sub_norm] if sub_norm else [])
                    conn.execute(
                        """
                        INSERT INTO tracked_domains (
                            domain, first_seen, last_seen, mention_count,
                            subreddits_json, domain_age_estimate, affiliate_hint
                        ) VALUES (?, ?, ?, 1, ?, ?, ?)
                        """,
                        (d, now, now, subs_json, age or "", aff),
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO tracked_domain_posts (domain, reddit_post_id, seen_at)
                        VALUES (?, ?, ?)
                        """,
                        (d, post_id, now),
                    )
                    result[d] = (True, 1)
                    continue

                prev_count = int(row[0] or 1)
                try:
                    subs_list = json.loads(row[1] or "[]")
                    if not isinstance(subs_list, list):
                        subs_list = []
                except json.JSONDecodeError:
                    subs_list = []
                if sub_norm and sub_norm not in subs_list:
                    subs_list.append(sub_norm)

                if new_post_for_domain:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO tracked_domain_posts (domain, reddit_post_id, seen_at)
                        VALUES (?, ?, ?)
                        """,
                        (d, post_id, now),
                    )
                    new_count = prev_count + 1
                    conn.execute(
                        """
                        UPDATE tracked_domains SET
                            last_seen = ?,
                            mention_count = ?,
                            subreddits_json = ?,
                            domain_age_estimate = COALESCE(NULLIF(?, ''), domain_age_estimate),
                            affiliate_hint = CASE WHEN ? = 1 THEN 1 ELSE affiliate_hint END
                        WHERE domain = ?
                        """,
                        (now, new_count, json.dumps(subs_list), age or "", aff, d),
                    )
                    result[d] = (False, new_count)
                else:
                    conn.execute(
                        """
                        UPDATE tracked_domains SET
                            last_seen = ?,
                            subreddits_json = ?,
                            domain_age_estimate = COALESCE(NULLIF(?, ''), domain_age_estimate),
                            affiliate_hint = CASE WHEN ? = 1 THEN 1 ELSE affiliate_hint END
                        WHERE domain = ?
                        """,
                        (now, json.dumps(subs_list), age or "", aff, d),
                    )
                    result[d] = (False, prev_count)

            conn.commit()
        return result

    def get_domain_row(self, domain: str) -> dict[str, Any] | None:
        d = domain.lower().strip()
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM tracked_domains WHERE domain = ?", (d,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_intel_float(self, key: str, default: float = 0.0) -> float:
        with self.connect() as conn:
            row = conn.execute("SELECT v FROM intel_kv WHERE k = ?", (key,)).fetchone()
            if row is None or row[0] is None:
                return default
            return float(row[0])

    def set_intel_float(self, key: str, val: float, ts: float | None = None) -> None:
        t = ts if ts is not None else time.time()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO intel_kv (k, v, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = excluded.updated_at
                """,
                (key, val, t),
            )
            conn.commit()

    def deferred_queue_count(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM deferred_scan_queue").fetchone()
            return int(row[0] or 0)

    def enqueue_deferred_scan(self, subreddit: str, priority: int, reason: str) -> None:
        now = time.time()
        sub = subreddit.strip()
        if not sub:
            return
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, priority FROM deferred_scan_queue WHERE subreddit = ?", (sub,)
            ).fetchone()
            if row:
                old_pri = int(row["priority"])
                if priority > old_pri:
                    conn.execute(
                        """
                        UPDATE deferred_scan_queue SET priority = ?, queued_at = ?, reason = ?
                        WHERE id = ?
                        """,
                        (priority, now, reason[:120], int(row["id"])),
                    )
                conn.commit()
                return
            conn.execute(
                """
                INSERT INTO deferred_scan_queue (subreddit, priority, queued_at, reason)
                VALUES (?, ?, ?, ?)
                """,
                (sub, priority, now, reason[:120]),
            )
            cnt = int(conn.execute("SELECT COUNT(*) FROM deferred_scan_queue").fetchone()[0])
            if cnt > 600:
                conn.execute(
                    """
                    DELETE FROM deferred_scan_queue WHERE id IN (
                        SELECT id FROM deferred_scan_queue
                        ORDER BY priority ASC, queued_at ASC LIMIT ?
                    )
                    """,
                    (cnt - 500,),
                )
            conn.commit()

    def pop_deferred_scans(self, limit: int) -> list[str]:
        if limit <= 0:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, subreddit FROM deferred_scan_queue
                ORDER BY priority DESC, queued_at ASC LIMIT ?
                """,
                (limit * 4,),
            ).fetchall()
            picked_ids: list[int] = []
            out: list[str] = []
            seen: set[str] = set()
            for r in rows:
                if len(out) >= limit:
                    break
                sid = str(r["subreddit"])
                sl = sid.lower()
                if sl in seen:
                    picked_ids.append(int(r["id"]))
                    continue
                seen.add(sl)
                out.append(sid)
                picked_ids.append(int(r["id"]))
            if picked_ids:
                qmarks = ",".join("?" * len(picked_ids))
                conn.execute(f"DELETE FROM deferred_scan_queue WHERE id IN ({qmarks})", picked_ids)
            conn.commit()
        return out

    def rank_subreddits_for_fetch(self, subs: list[str]) -> list[str]:
        hp = {x.lower() for x in HIGH_PRIORITY_SUBREDDITS}
        mp = {x.lower() for x in MEDIUM_PRIORITY_SUBREDDITS}
        with self.connect() as conn:
            rows = conn.execute("SELECT subreddit, quality_score FROM subreddit_stats").fetchall()
        qmap = {str(r["subreddit"]).lower(): float(r["quality_score"]) for r in rows}

        def sort_key(s: str) -> tuple[float, str]:
            sl = s.lower()
            tier = 220.0 if sl in hp else 110.0 if sl in mp else 0.0
            q = qmap.get(sl, 50.0)
            return (-tier - q, sl)

        return sorted(subs, key=sort_key)

    def record_subreddit_post_intel(
        self,
        subreddit: str,
        *,
        scam_p: float,
        gem: float,
        opp: float,
        sat: float,
        complaint_score: float,
        confirm_weight: float,
    ) -> tuple[float, float]:
        """Rolling aggregates → quality_score & decay_score. Returns (quality, decay)."""
        sl = subreddit.strip().lower()
        now = time.time()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM subreddit_stats WHERE subreddit = ?", (sl,)
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO subreddit_stats (
                        subreddit, posts_sampled, scam_sum, confirm_weight_sum,
                        gem_sum, opp_sum, sat_sum, complaint_sum,
                        quality_score, decay_score, updated_at
                    ) VALUES (?, 1, ?, ?, ?, ?, ?, ?, 50, 0, ?)
                    """,
                    (sl, scam_p, confirm_weight, gem, opp, sat, complaint_score, now),
                )
                conn.commit()
                return (50.0, 0.0)

            p = int(row["posts_sampled"]) + 1
            scam_sum = float(row["scam_sum"]) + scam_p
            cw_sum = float(row["confirm_weight_sum"]) + confirm_weight
            gem_sum = float(row["gem_sum"]) + gem
            opp_sum = float(row["opp_sum"]) + opp
            sat_sum = float(row["sat_sum"]) + sat
            comp_sum = float(row["complaint_sum"]) + complaint_score

            scam_avg = scam_sum / p
            gem_avg = gem_sum / p
            opp_avg = opp_sum / p
            sat_avg = sat_sum / p
            compl_avg = comp_sum / p
            cw_avg = cw_sum / p

            quality = (
                50.0
                + (opp_avg - 50.0) * 0.38
                + (gem_avg - 50.0) * 0.22
                + min(18.0, cw_avg * 4.0)
                - scam_avg * 0.28
                - compl_avg * 0.35
            )
            quality = max(5.0, min(95.0, quality))

            decay = min(
                100.0,
                compl_avg * 0.85 + scam_avg * 0.35 + sat_avg * 0.18 - min(25.0, cw_avg * 3.0),
            )
            decay = max(0.0, decay)

            conn.execute(
                """
                UPDATE subreddit_stats SET
                    posts_sampled = ?, scam_sum = ?, confirm_weight_sum = ?,
                    gem_sum = ?, opp_sum = ?, sat_sum = ?, complaint_sum = ?,
                    quality_score = ?, decay_score = ?, updated_at = ?
                WHERE subreddit = ?
                """,
                (p, scam_sum, cw_sum, gem_sum, opp_sum, sat_sum, comp_sum, quality, decay, now, sl),
            )
            conn.commit()
            return (quality, decay)

    def get_poster_reliability(self, author: str) -> float:
        a = (author or "").strip().lower()
        if not a or a in ("[deleted]", "none"):
            return 50.0
        with self.connect() as conn:
            row = conn.execute(
                "SELECT reliability_score FROM poster_stats WHERE author = ?", (a,)
            ).fetchone()
            return float(row[0]) if row else 50.0

    def touch_poster_intel(self, author: str, confirm_delta: float, complaint_delta: int) -> float:
        a = (author or "").strip().lower()
        if not a or a in ("[deleted]", "none", "automoderator"):
            return 50.0
        now = time.time()
        cd = max(0.0, confirm_delta)
        cp = max(0, complaint_delta)
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM poster_stats WHERE author = ?", (a,)).fetchone()
            if row is None:
                rel = max(12.0, min(92.0, 48.0 + math.log1p(cd + 1.0) * 6.5 - cp * 8.0))
                conn.execute(
                    """
                    INSERT INTO poster_stats (
                        author, posts, confirm_weight, complaint_events,
                        reliability_score, updated_at
                    ) VALUES (?, 1, ?, ?, ?, ?)
                    """,
                    (a, cd, cp, rel, now),
                )
            else:
                posts = int(row["posts"]) + 1
                cw = float(row["confirm_weight"]) + cd
                ce = int(row["complaint_events"]) + cp
                rel = max(12.0, min(92.0, 48.0 + math.log1p(cw + 1.0) * 6.5 - ce * 8.0))
                conn.execute(
                    """
                    UPDATE poster_stats SET posts = ?, confirm_weight = ?, complaint_events = ?,
                    reliability_score = ?, updated_at = ? WHERE author = ?
                    """,
                    (posts, cw, ce, rel, now, a),
                )
            conn.commit()
            r = conn.execute(
                "SELECT reliability_score FROM poster_stats WHERE author = ?", (a,)
            ).fetchone()
            return float(r[0]) if r else 50.0
