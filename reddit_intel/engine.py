"""Fetch cycle: subreddit new posts → dedupe → scores → DB → alerts."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import praw

from reddit_intel.alerts import (
    format_alert,
    format_early_gem_alert,
    format_priority_override_alert,
    notify_alert_destinations,
    send_console_alert,
)
from reddit_intel.comment_intel import CommentIntelResult, scan_submission_comments
from reddit_intel.config import (
    ALERT_MIN_OPPORTUNITY_SCORE,
    ALERT_MIN_PAYOUT_USD,
    CHECK_URL_INTEGRITY,
    COMMENT_SAMPLE_LIMIT,
    EARLY_GEM_FIRST_MOVER_MIN,
    EARLY_GEM_MAX_MENTIONS,
    EARLY_GEM_MAX_SATURATION,
    EARLY_GEM_MAX_SCAM_PROB,
    EARLY_GEM_MIN_TRUST,
    EXCLUDED_SUBREDDITS,
    FETCH_COMMENT_SAMPLES,
    MONITORED_SUBREDDITS,
    POSTS_PER_SUB_FETCH,
    USA_ONLY_STRICT,
)
from reddit_intel.database import Database
from reddit_intel.dedupe import build_canonical_offer_id, guess_company_slug, merge_unique_lists
from reddit_intel.detectors import (
    classify_offer_type,
    early_signal_hit_count,
    extract_money_amounts,
    extract_urls,
    geo_excludes_usa,
    keyword_hit_count,
    urgency_hits,
)
from reddit_intel.intelligence_signals import (
    apply_daily_learning_adjustments,
    competition_density_score,
    complaint_score_from_rates,
    engagement_acceleration_score,
    estimated_maximized_reward_hint,
    estimated_saturation_hours_remaining,
    fatigue_score,
    merge_eligible_states_json,
    merge_excluded_states_json,
    negative_sentiment_hits,
    offer_integrity_score_from_probe,
    payout_failure_rate,
    recurring_bonus_probability,
    stackability_score,
    state_coverage_score,
    temporary_boost_score,
    unique_authors_from_sources,
    weighted_confirmation_score_norm,
    withdrawal_friction_hits,
    withdrawal_friction_score,
)
from reddit_intel.throttle import get_throttle
from reddit_intel.url_probe import probe_url_health
from reddit_intel.entity_intel import (
    affiliate_system_hint,
    domain_age_estimate_heuristic,
    early_gem_explanation,
    estimated_profit_window,
    extract_external_domains,
    first_mover_score,
    is_known_brand_slug,
    launch_status_label,
    predicted_growth_score,
    saturation_risk_score,
    startup_legitimacy_score,
)
from reddit_intel.report_builder import build_report
from reddit_intel.scoring import (
    difficulty_score,
    engagement_score,
    hidden_gem_score,
    opportunity_score,
    saturation_score,
    scam_probability,
    summarize_strategy,
    trust_score,
    trend_velocity_label,
)


def _should_ingest(text: str) -> bool:
    if keyword_hit_count(text) >= 1:
        return True
    if early_signal_hit_count(text) >= 1:
        return True
    if extract_money_amounts(text):
        return True
    low = text.lower()
    return "http" in low and ("refer" in low or "signup" in low or "promo" in low)


def _ai_summary(title: str, body: str, offer_type: str) -> str:
    blob = f"{title}\n{body or ''}".strip()[:800]
    return f"[{offer_type}] {blob}".replace("\n", " ")


def _trust_reasoning(scam_p: float, confirms: int, brand: str) -> str:
    parts = [f"Brand anchor {brand}.", f"Scam heuristics ~{scam_p:.0f}/100."]
    if confirms:
        parts.append(f"{confirms} payout-confirmation phrase hits in sampled comments.")
    else:
        parts.append("No payout phrases in sampled comments.")
    return " ".join(parts)


def _risk_explanation(text: str, scam_p: float) -> str:
    if scam_p >= 55:
        return "Elevated risk: multiple scam-like phrases or suspicious link patterns."
    if scam_p >= 35:
        return "Moderate risk: verify domain and program legitimacy."
    return "Baseline referral noise; still verify terms independently."


def _safe_json_list(existing: dict[str, Any] | None, key: str) -> list[str]:
    if not existing:
        return []
    try:
        val = json.loads(existing[key] or "[]")
        return [str(x) for x in val] if isinstance(val, list) else []
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def _merge_sources(existing: list[dict], entry: dict) -> list[dict]:
    ids = {e.get("reddit_id") for e in existing}
    if entry.get("reddit_id") not in ids:
        existing = [*existing, entry]
    return existing


def process_submission(
    sub: "praw.models.Submission",
    db: Database,
    fetch_comments: bool = True,
    comment_sample_cap: int | None = None,
) -> str | None:
    subreddit = str(sub.subreddit).lower()
    if subreddit in {x.lower() for x in EXCLUDED_SUBREDDITS}:
        return None

    title = sub.title or ""
    body = getattr(sub, "selftext", "") or ""
    text = f"{title}\n{body}"
    if not _should_ingest(text):
        return None
    if USA_ONLY_STRICT and geo_excludes_usa(text):
        return None

    now = time.time()
    reddit_id = sub.name if hasattr(sub, "name") else sub.id
    # PRAW: fullname t3_xxxxx
    if not str(reddit_id).startswith("t3_"):
        reddit_id = f"t3_{sub.id}"

    permalink = sub.permalink if sub.permalink.startswith("/") else "/" + sub.permalink
    poster_author = str(sub.author) if sub.author else ""
    raw_row = {
        "reddit_id": reddit_id,
        "subreddit": str(sub.subreddit),
        "title": title,
        "body": body,
        "url": getattr(sub, "url", "") or "",
        "permalink": permalink,
        "author": poster_author,
        "score": int(sub.score or 0),
        "num_comments": int(sub.num_comments or 0),
        "created_utc": float(sub.created_utc),
        "fetched_at": now,
        "is_comment": 0,
        "parent_post_reddit_id": None,
        "raw_json": None,
    }
    db.upsert_raw_post(raw_row)

    offer_type = classify_offer_type(text)
    cid = build_canonical_offer_id(title, body, offer_type)
    brand = guess_company_slug(text)

    amounts = extract_money_amounts(text)
    max_reward = max(amounts) if amounts else 0.0
    reward_str = f"${max_reward:g}" if max_reward else ""

    dd_req = "direct deposit" in text.lower()
    ssn_req = "ssn" in text.lower() or "social security" in text.lower()
    deposit_req = any(x in text.lower() for x in ("minimum deposit", "fund account", "deposit $"))

    existing = db.get_canonical(cid)
    already_linked = db.is_offer_post_linked(cid, reddit_id)

    cap = comment_sample_cap if comment_sample_cap is not None else COMMENT_SAMPLE_LIMIT
    ci = CommentIntelResult(0, 0, 0.0, 0.0, 0, 0)
    if fetch_comments and not already_linked and sub.num_comments and sub.num_comments > 0:
        try:
            ci = scan_submission_comments(sub, cap)
        except Exception:
            pass

    confirms = ci.payout_confirmation_lines

    if not already_linked:
        db.touch_poster_intel(
            poster_author,
            ci.weighted_positive_sum if fetch_comments else 0.0,
            1 if (fetch_comments and ci.negative_lines > 0) else 0,
        )
    poster_rel = db.get_poster_reliability(poster_author)

    urls = extract_urls(text)
    if getattr(sub, "url", "") and "reddit.com" not in sub.url:
        urls.insert(0, sub.url)
    domains = extract_external_domains(urls)
    primary_domain = domains[0] if domains else ""

    domain_touch: dict[str, tuple[bool, int]] = {}
    if domains:
        domain_age_estimates = {d: domain_age_estimate_heuristic(d) for d in domains}
        affiliate_hints = {d: affiliate_system_hint(d) for d in domains}
        domain_touch = db.touch_domains(
            domains,
            str(sub.subreddit),
            reddit_id,
            now,
            domain_age_estimates,
            affiliate_hints,
        )
    primary_first_insert = (
        domain_touch.get(primary_domain, (False, 0))[0] if primary_domain else False
    )

    prev_refs: list[str] = []
    if existing:
        try:
            loaded = json.loads(existing["referral_links_json"] or "[]")
            if isinstance(loaded, list):
                prev_refs = [str(x) for x in loaded]
        except json.JSONDecodeError:
            prev_refs = []
    referral_links = merge_unique_lists(prev_refs, urls[:15])

    early_signal_count = early_signal_hit_count(text)
    is_unknown_entity = not is_known_brand_slug(brand)

    urgent = bool(urgency_hits(text))
    kw = keyword_hit_count(text)
    kw_eff = kw + early_signal_count

    subs_prev = []
    sources_prev = []
    if existing:
        subs_prev = json.loads(existing["subreddits_json"] or "[]")
        if not isinstance(subs_prev, list):
            subs_prev = []
        sources_prev = json.loads(existing["source_posts_json"] or "[]")
        if not isinstance(sources_prev, list):
            sources_prev = []

    subs_merged = merge_unique_lists(subs_prev, [str(sub.subreddit)])
    sources_merged = _merge_sources(
        sources_prev,
        {
            "reddit_id": reddit_id,
            "permalink": permalink,
            "title": title,
            "score": int(sub.score or 0),
            "author": poster_author,
        },
    )

    mentions = len(sources_merged)

    prev_conf = int(existing["confirmation_count"] or 0) if existing else 0
    confirmation_count = prev_conf + confirms

    score_sum = sum(int(s.get("score") or 0) for s in sources_merged if isinstance(s, dict))
    scam_p = scam_probability(text)
    trust_base = trust_score(text, confirmation_count, mentions, str(sub.subreddit))
    sat = saturation_score(mentions, len(set(subs_merged)), float(score_sum))
    diff = difficulty_score(text, dd_req, ssn_req)

    has_https = any((u or "").lower().startswith("https") for u in urls)
    startup_legit = startup_legitimacy_score(
        text,
        domains,
        scam_p,
        confirmation_count,
        early_signal_count,
        has_https,
    )

    eng = engagement_score(int(sub.score or 0), int(sub.num_comments or 0), kw_eff)
    prev_mentions = len(sources_prev) if existing else 0
    trend = trend_velocity_label(mentions, max(1, prev_mentions))

    post_age_h = max(1.0 / 3600.0, (now - float(sub.created_utc)) / 3600.0)
    eng_accel = engagement_acceleration_score(
        int(sub.score or 0),
        int(sub.num_comments or 0),
        post_age_h,
        len(set(subs_merged)),
        trend,
    )

    fms = first_mover_score(
        sat,
        max_reward,
        mentions,
        is_unknown_entity,
        early_signal_count,
        primary_first_insert,
        trend,
        eng,
        startup_legit,
    )

    predicted_growth = predicted_growth_score(
        trend,
        early_signal_count,
        eng,
        len(set(subs_merged)),
        max_reward,
    )
    sat_risk = saturation_risk_score(trend, mentions, early_signal_count, sat)
    profit_window = estimated_profit_window(urgent, sat_risk, predicted_growth, text)
    launch_stat = launch_status_label(
        text, early_signal_count, is_unknown_entity, primary_first_insert
    )

    gem = hidden_gem_score(
        int(sub.score or 0),
        int(sub.num_comments or 0),
        sat,
        max_reward,
        trust_base,
        first_mover=fms,
    )

    opp_raw = opportunity_score(
        trust_base,
        gem,
        max_reward,
        scam_p,
        sat,
        urgent,
        kw,
        first_mover=fms,
        mentions_count=mentions,
        early_signal_count=early_signal_count,
    )

    body_neg = len(negative_sentiment_hits(text))
    complaint_score = complaint_score_from_rates(
        ci.negative_lines, ci.withdrawal_lines, ci.comments_sampled, body_neg
    )
    payout_fail_rate = payout_failure_rate(ci.negative_lines, ci.comments_sampled)
    wd_friction = withdrawal_friction_score(
        ci.withdrawal_lines, ci.comments_sampled, len(withdrawal_friction_hits(text))
    )
    weighted_conf = weighted_confirmation_score_norm(
        ci.weighted_positive_sum, ci.repetitive_confirmation_penalty, ci.comments_sampled
    )

    competition = competition_density_score(
        unique_authors_from_sources(sources_merged), mentions, referral_links
    )
    fatigue = fatigue_score(sat, mentions, complaint_score, competition)

    prev_m_db = int(existing["mentions_count"] or 0) if existing else 0
    prev_ts_db = float(existing["latest_seen"] or existing["first_seen"]) if existing else now
    dt_h = max(1e-6, (now - prev_ts_db) / 3600.0)
    mention_rate = (mentions - prev_m_db) / dt_h
    sat_hours = estimated_saturation_hours_remaining(sat, sat_risk, mention_rate)
    decay_vel = mention_rate - complaint_score * 0.35 - fatigue * 0.12

    integrity_score = 72.0
    if CHECK_URL_INTEGRITY:
        for u in referral_links:
            if u.startswith("http"):
                ok, timed_out = probe_url_health(u)
                integrity_score = offer_integrity_score_from_probe(ok, timed_out)
                break

    eligible_states_json = merge_eligible_states_json(
        existing.get("eligible_states_json") if existing else None, text
    )
    excluded_states_json = merge_excluded_states_json(
        existing.get("excluded_states_json") if existing else None, text
    )
    try:
        elig_list = json.loads(eligible_states_json)
        excl_list = json.loads(excluded_states_json)
        if not isinstance(elig_list, list):
            elig_list = []
        if not isinstance(excl_list, list):
            excl_list = []
    except json.JSONDecodeError:
        elig_list, excl_list = [], []
    state_cov = state_coverage_score(elig_list, excl_list)

    temp_boost = temporary_boost_score(text)
    recurring_prob = recurring_bonus_probability(text)
    stack_score = stackability_score(text, offer_type)
    est_max_reward = estimated_maximized_reward_hint(max_reward, stack_score, temp_boost)

    trust_mid = trust_base + weighted_conf * 0.07 + (poster_rel - 50.0) * 0.11
    trust_mid += state_cov * 0.055 + temp_boost * 0.045 + eng_accel * 0.035
    trust_mid -= complaint_score * 0.42 + payout_fail_rate * 0.26 + fatigue * 0.09
    trust_mid -= wd_friction * 0.06 + max(0.0, 85.0 - integrity_score) * 0.07
    trust_mid = max(0.0, min(100.0, trust_mid))

    opp_mid = opp_raw + eng_accel * 0.055 + temp_boost * 0.065 + stack_score * 0.035
    opp_mid += (poster_rel - 50.0) * 0.025 + state_cov * 0.025
    opp_mid -= fatigue * 0.11 + competition * 0.09
    opp_mid -= max(0.0, 78.0 - integrity_score) * 0.055
    opp_mid = max(0.0, min(100.0, opp_mid))

    gem_mid = max(0.0, min(100.0, gem + weighted_conf * 0.06 - fatigue * 0.05))

    sq, sd = db.record_subreddit_post_intel(
        str(sub.subreddit),
        scam_p=scam_p,
        gem=gem_mid,
        opp=opp_mid,
        sat=sat,
        complaint_score=complaint_score,
        confirm_weight=ci.weighted_positive_sum if fetch_comments else 0.0,
    )

    trust_fin, learn_dt, learn_ds = apply_daily_learning_adjustments(trust_mid, scam_p, sq, sd)
    scam_fin = max(0.0, min(100.0, scam_p + learn_ds))

    risk = min(100.0, scam_fin * 0.85 + (30.0 if deposit_req else 5.0))

    th = get_throttle()
    queue_depth = db.deferred_queue_count()

    first_seen = float(existing["first_seen"]) if existing else now
    reasoning = _trust_reasoning(scam_fin, confirms, brand)
    risk_expl = _risk_explanation(text, scam_fin)
    summary = _ai_summary(title, body, offer_type)
    strategy = summarize_strategy(text, offer_type)

    fields: dict[str, Any] = {
        "canonical_offer_id": cid,
        "company_name": brand.replace("_", " ").title() if brand != "UNKNOWN_BRAND" else title[:80],
        "offer_type": offer_type,
        "reward_amount": reward_str or (existing or {}).get("reward_amount") or "",
        "currency": "USD",
        "deposit_required": int(deposit_req),
        "direct_deposit_required": int(dd_req),
        "ssn_required": int(ssn_req),
        "minimum_deposit": "",
        "withdrawal_minimum": "",
        "requirements_json": json.dumps(
            merge_unique_lists(
                _safe_json_list(existing, "requirements_json"),
                (["direct_deposit"] if dd_req else []) + (["ssn"] if ssn_req else []),
            )
        ),
        "eligible_states_json": eligible_states_json,
        "excluded_states_json": excluded_states_json,
        "payout_methods_json": json.dumps([]),
        "platforms_json": json.dumps(["reddit"]),
        "promo_codes_json": json.dumps([]),
        "referral_links_json": json.dumps(referral_links),
        "expiration_date": "",
        "estimated_completion_time": "",
        "difficulty_score": diff,
        "risk_score": risk,
        "scam_probability": scam_fin,
        "trust_score": trust_fin,
        "hidden_gem_score": gem_mid,
        "opportunity_score": opp_mid,
        "engagement_score": eng,
        "saturation_score": sat,
        "mentions_count": mentions,
        "confirmation_count": confirmation_count,
        "trend_velocity": trend,
        "subreddits_json": json.dumps(subs_merged),
        "source_posts_json": json.dumps(sources_merged),
        "ai_summary": summary,
        "best_signup_strategy": strategy,
        "trust_reasoning": reasoning,
        "risk_explanation": risk_expl,
        "first_seen": first_seen,
        "latest_seen": now,
        "urgent": int(urgent),
        "merged_engagement_score": float(score_sum),
        "updated_at": now,
        "first_mover_score": fms,
        "predicted_growth_score": predicted_growth,
        "saturation_risk": sat_risk,
        "estimated_profit_window": profit_window,
        "startup_legitimacy_score": startup_legit,
        "is_unknown_entity": int(is_unknown_entity),
        "launch_status": launch_stat,
        "primary_domain": primary_domain,
        "engagement_acceleration_score": eng_accel,
        "estimated_saturation_hours_remaining": sat_hours,
        "payout_failure_rate": payout_fail_rate,
        "complaint_score": complaint_score,
        "competition_density_score": competition,
        "state_coverage_score": state_cov,
        "withdrawal_friction_score": wd_friction,
        "recurring_bonus_probability": recurring_prob,
        "poster_reliability_score": poster_rel,
        "fatigue_score": fatigue,
        "offer_integrity_score": integrity_score,
        "temporary_boost_score": temp_boost,
        "weighted_confirmation_score": weighted_conf,
        "stackability_score": stack_score,
        "estimated_maximized_reward": est_max_reward,
        "decay_velocity": decay_vel,
        "learning_trust_delta": learn_dt,
        "learning_scam_delta": learn_ds,
        "mentions_prior_snapshot": mentions,
        "prior_refresh_ts": now,
        "api_pressure_score_snapshot": th.api_pressure_score,
        "deferred_queue_depth_snapshot": queue_depth,
    }

    db.upsert_canonical_offer(cid, fields)
    db.link_offer_post(cid, reddit_id)

    _maybe_fire_alert(db, fields)
    _maybe_fire_early_gem_alert(db, fields)
    _maybe_fire_priority_override_alert(db, fields)
    return cid


def _maybe_fire_alert(db: Database, fields: dict[str, Any]) -> None:
    max_reward = 0.0
    try:
        ra = str(fields.get("reward_amount", "")).replace("$", "").strip()
        max_reward = float(ra) if ra else 0.0
    except ValueError:
        pass

    opp = float(fields.get("opportunity_score") or 0)
    gem = float(fields.get("hidden_gem_score") or 0)
    urgent = bool(fields.get("urgent"))
    ot = str(fields.get("offer_type") or "")
    trust = float(fields.get("trust_score") or 0)

    hit = False
    if max_reward >= ALERT_MIN_PAYOUT_USD:
        hit = True
    if opp >= ALERT_MIN_OPPORTUNITY_SCORE:
        hit = True
    if gem >= 70:
        hit = True
    if urgent and trust >= 40:
        hit = True
    if ot in ("bank_bonus", "brokerage", "sportsbook") and max_reward >= 15:
        hit = True
    if ot == "crypto_signup" and max_reward >= 25:
        hit = True

    if not hit:
        return

    cid = str(fields["canonical_offer_id"])
    last = db.last_alert_time(cid, "standard")
    if last is not None and time.time() - last < 3600:
        return

    reqs = []
    try:
        reqs = json.loads(fields.get("requirements_json") or "[]")
    except json.JSONDecodeError:
        pass

    sources = json.loads(fields.get("source_posts_json") or "[]")
    reddit_links: list[str] = []
    if isinstance(sources, list):
        for s in sources:
            if isinstance(s, dict) and s.get("permalink"):
                reddit_links.append(f"https://reddit.com{s['permalink']}")
    refurls_raw = json.loads(fields.get("referral_links_json") or "[]")
    referral_links: list[str] = []
    if isinstance(refurls_raw, list):
        for u in refurls_raw:
            su = str(u or "")
            if su and "reddit.com" not in su:
                referral_links.append(su)

    try:
        subs_list = json.loads(fields.get("subreddits_json") or "[]")
        primary_sub = subs_list[0] if isinstance(subs_list, list) and subs_list else ""
    except json.JSONDecodeError:
        primary_sub = ""

    payload = {
        "company_name": fields.get("company_name"),
        "reward_amount": fields.get("reward_amount"),
        "offer_type": fields.get("offer_type"),
        "subreddit": primary_sub,
        "first_seen": fields.get("first_seen"),
        "requirements": ", ".join(reqs) if reqs else "",
        "deposit_needed": bool(fields.get("deposit_required")),
        "trust_score": round(trust, 1),
        "mentions": fields.get("mentions_count"),
        "trend_velocity": fields.get("trend_velocity"),
        "hidden_gem_score": round(gem, 1),
        "opportunity_score": round(opp, 1),
        "ai_summary": fields.get("ai_summary"),
        "reddit_links": reddit_links[:3],
        "referral_links": referral_links[:4],
    }
    text = format_alert(payload)
    send_console_alert(text)
    notify_alert_destinations(text)
    db.log_alert(cid, payload, alert_kind="standard")


def _risk_level_label(risk: float) -> str:
    if risk >= 72:
        return "high"
    if risk >= 46:
        return "medium"
    return "low"


def _maybe_fire_early_gem_alert(db: Database, fields: dict[str, Any]) -> None:
    launch_stat = str(fields.get("launch_status") or "")
    fresh_domain = "first_seen_domain" in launch_stat

    sat = float(fields.get("saturation_score") or 0)
    mentions = int(fields.get("mentions_count") or 0)
    trust = float(fields.get("trust_score") or 0)
    scam_p = float(fields.get("scam_probability") or 0)
    fms = float(fields.get("first_mover_score") or 0)
    risk = float(fields.get("risk_score") or 0)

    unknown_hit = bool(int(fields.get("is_unknown_entity") or 0)) or fresh_domain
    if not unknown_hit:
        return
    if sat >= EARLY_GEM_MAX_SATURATION:
        return
    if mentions > EARLY_GEM_MAX_MENTIONS:
        return
    if trust + 1e-9 < EARLY_GEM_MIN_TRUST:
        return
    if scam_p >= EARLY_GEM_MAX_SCAM_PROB:
        return
    if fms <= EARLY_GEM_FIRST_MOVER_MIN:
        return

    cid = str(fields["canonical_offer_id"])
    last = db.last_alert_time(cid, "early_gem")
    if last is not None and time.time() - last < 7200:
        return

    why, pot = early_gem_explanation(
        str(fields.get("company_name", "")),
        fms,
        bool(int(fields.get("is_unknown_entity") or 0)),
        fresh_domain,
        sat,
        float(fields.get("startup_legitimacy_score") or 0),
    )
    pg = float(fields.get("predicted_growth_score") or 0)
    sr = float(fields.get("saturation_risk") or 0)
    ew = str(fields.get("estimated_profit_window") or "")
    pot = (
        f"{pot} Predicted-growth heuristic ~{pg:.0f}/100; saturation-risk ~{sr:.0f}/100. "
        f"Window hint: {ew}"
    )

    try:
        subs = json.loads(fields.get("subreddits_json") or "[]")
        sub_s = ", ".join(subs) if isinstance(subs, list) else str(subs)
    except json.JSONDecodeError:
        sub_s = ""

    fs_ts = float(fields.get("first_seen") or time.time())
    first_seen_s = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(fs_ts))

    sources = json.loads(fields.get("source_posts_json") or "[]")
    reddit_links: list[str] = []
    if isinstance(sources, list):
        for s in sources:
            if isinstance(s, dict) and s.get("permalink"):
                reddit_links.append(f"https://reddit.com{s['permalink']}")
    refurls_raw = json.loads(fields.get("referral_links_json") or "[]")
    referral_links: list[str] = []
    if isinstance(refurls_raw, list):
        for u in refurls_raw:
            su = str(u or "")
            if su and "reddit.com" not in su:
                referral_links.append(su)

    pd = str(fields.get("primary_domain") or "").strip()
    app_site = str(fields.get("company_name", ""))
    if pd:
        app_site = f"{app_site} ({pd})"

    payload = {
        "app_site": app_site,
        "reward_amount": fields.get("reward_amount"),
        "launch_status": launch_stat,
        "first_seen": first_seen_s,
        "first_seen_ts": fs_ts,
        "subreddits": sub_s,
        "mentions": mentions,
        "first_mover_score": round(fms, 1),
        "trust_score": round(trust, 1),
        "risk_level": _risk_level_label(risk),
        "why_it_matters": why,
        "potential": pot,
        "reddit_links": reddit_links[:3],
        "referral_links": referral_links[:4],
    }
    text = format_early_gem_alert(payload)
    send_console_alert(text)
    notify_alert_destinations(text)
    db.log_alert(cid, payload, alert_kind="early_gem")


def _maybe_fire_priority_override_alert(db: Database, fields: dict[str, Any]) -> None:
    launch_stat = str(fields.get("launch_status") or "")
    fresh_domain = "first_seen_domain" in launch_stat
    unknown = bool(int(fields.get("is_unknown_entity") or 0))
    if not (fresh_domain or unknown):
        return

    fms = float(fields.get("first_mover_score") or 0)
    eng_a = float(fields.get("engagement_acceleration_score") or 0)
    comp = float(fields.get("competition_density_score") or 0)
    mentions = int(fields.get("mentions_count") or 0)
    complaint = float(fields.get("complaint_score") or 0)
    wconf = float(fields.get("weighted_confirmation_score") or 0)

    if fms <= 78:
        return
    if eng_a <= 62:
        return
    if comp >= 58:
        return
    if mentions > 16:
        return
    if complaint >= 42:
        return
    if wconf <= 38:
        return

    cid = str(fields["canonical_offer_id"])
    last_po = db.last_alert_time(cid, "priority_override")
    if last_po is not None and time.time() - last_po < 1800:
        return

    sources = json.loads(fields.get("source_posts_json") or "[]")
    reddit_links: list[str] = []
    if isinstance(sources, list):
        for s in sources:
            if isinstance(s, dict) and s.get("permalink"):
                reddit_links.append(f"https://reddit.com{s['permalink']}")
    refurls_raw = json.loads(fields.get("referral_links_json") or "[]")
    referral_links: list[str] = []
    if isinstance(refurls_raw, list):
        for u in refurls_raw:
            su = str(u or "")
            if su and "reddit.com" not in su:
                referral_links.append(su)

    why = (
        "Pre-saturation signal: new/fresh footprint + accelerating engagement + credible-weight "
        "confirmations + low referral crowding."
    )
    payload = {
        "target": fields.get("company_name"),
        "reward_amount": fields.get("reward_amount"),
        "first_mover_score": round(fms, 1),
        "engagement_acceleration_score": round(eng_a, 1),
        "weighted_confirmation_score": round(wconf, 1),
        "competition_density_score": round(comp, 1),
        "mentions": mentions,
        "estimated_saturation_hours_remaining": round(
            float(fields.get("estimated_saturation_hours_remaining") or 0), 1
        ),
        "why": why,
        "reddit_links": reddit_links[:3],
        "referral_links": referral_links[:4],
    }
    text = format_priority_override_alert(payload)
    send_console_alert(text)
    notify_alert_destinations(text)
    db.log_alert(cid, payload, alert_kind="priority_override")


def run_fetch_cycle(reddit: "praw.Reddit", db: Database) -> int:
    th = get_throttle()
    th.load_from_db(db)
    th.decay_tick_at_cycle_start()

    ranked = db.rank_subreddits_for_fetch(list(MONITORED_SUBREDDITS))
    frac = th.deferral_fraction()
    keep_n = max(16, int(len(ranked) * (1.0 - frac)))

    recovery: list[str] = []
    if th.api_pressure_score < 44:
        recovery = db.pop_deferred_scans(min(12, max(3, len(ranked) // 4)))

    if frac > 0:
        for s in ranked[keep_n:]:
            db.enqueue_deferred_scan(s, priority=0, reason="api_pressure_budget")

    fetch_order = list(dict.fromkeys(recovery + ranked[:keep_n]))

    fc_global = FETCH_COMMENT_SAMPLES and not th.force_skip_comments_entirely()
    cap = COMMENT_SAMPLE_LIMIT
    if th.should_reduce_comment_scanning():
        cap = max(4, COMMENT_SAMPLE_LIMIT // 3)

    count = 0
    try:
        for sub_name in fetch_order:
            time.sleep(th.sleep_backoff_seconds())
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.new(limit=POSTS_PER_SUB_FETCH):
                    if process_submission(
                        post, db, fetch_comments=fc_global, comment_sample_cap=cap
                    ):
                        count += 1
            except Exception as ex:
                low = str(ex).lower()
                if (
                    "429" in low
                    or "too many requests" in low
                    or "ratelimit" in low
                    or "TooManyRequests" in type(ex).__name__
                ):
                    th.record_rate_limited()
                    db.enqueue_deferred_scan(sub_name, priority=10, reason="rate_limit")
                continue
    finally:
        th.persist(db)
    return count


def run_report(db: Database, window_seconds: float) -> str:
    end = time.time()
    start = end - window_seconds
    rows = db.fetch_offers_in_window(start, end)
    md = build_report(rows, start, end)
    db.log_report(start, end, md)
    return md
