"""Lifecycle email: segment registry, idempotent runner, and event-driven sends.

The backend plans, the founder approves: ``run()`` defaults to a dry run, and a real run is refused
(``refused_reason``) unless the ``lifecycle_emails`` flag is on and the sender config is present.
Every send goes through ``email_service.send_tracked``, whose unique ``dedupe_key`` makes a re-run,
a double trigger or an event racing the daily backstop send nothing twice.

Segments are windows over real DB state, not exact days, so a skipped day only delays an email and
stale steps expire. Inputs: users.created_at, cli_auth_codes.used_at (a finished CLI login),
submissions status/started_at/scored_at, developer_profiles.free_submissions_used and email_sends.
PostHog is write-only from here, so no segment reads it.

Rules (growth blueprint, section 6):
  - base filter: developer, not banned, not demo (is_demo or @demo.kodwai.dev), not INTERNAL_EMAILS,
    not unsubscribed, not suppressed, and verified (unverified only for verify_reminder)
  - one email per user per run; at most 1 lifecycle email per 24 h and 3 per 7 days
  - nothing while the user started or scored a submission in the last 24 h
  - milestones (first_score) are exempt from the caps and the activity rule
  - the activation drip (d1_start, d3_first_submit, stalled_submission, d7_not_scored) exits after the
    first scored submission; d7_scored and reengage are the post-score steps
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.database import fetch_all, fetch_one
from app.services import email_templates, entitlement_service
from app.services.email_service import MAX_SEND_ATTEMPTS, mask_email, send_tracked
from app.services.email_templates import RenderedEmail, app_url, first_name
from app.services.feature_flags import flag_active_by_key

logger = logging.getLogger(__name__)

LIFECYCLE_FLAG = "lifecycle_emails"
DAILY_CAP = 1
WEEKLY_CAP = 3
REENGAGE_MAX_SENDS = 2

# Statuses that mean "an email went (or is going) to this user in this run".
_SENT_LIKE = ("sent", "dry_run", "refused", "failed")

# Per-user state every segment filters on. {base} is the base filter; the runner wraps this in
# SELECT * FROM (...) st WHERE <segment_sql>, so segments reference these columns by name.
_STATE_SQL = """
SELECT
    u.id AS user_id,
    u.email AS email,
    u.name AS name,
    u.created_at AS created_at,
    u.email_verified AS email_verified,
    u.email_verification_token AS verification_token,
    (julianday('now') - julianday(u.created_at)) * 24 AS age_hours,
    EXISTS (SELECT 1 FROM cli_auth_codes c WHERE c.user_id = u.id AND c.used_at IS NOT NULL) AS has_cli_login,
    (SELECT COUNT(*) FROM submissions s WHERE s.user_id = u.id) AS submissions_started,
    (SELECT COUNT(*) FROM submissions s WHERE s.user_id = u.id AND s.status != 'error') AS submissions_active,
    (SELECT COUNT(*) FROM submissions s WHERE s.user_id = u.id AND s.status = 'scored') AS scored_count,
    (julianday('now') - (SELECT MIN(julianday(s.scored_at)) FROM submissions s
        WHERE s.user_id = u.id AND s.status = 'scored' AND s.leaderboard_eligible = 1)) * 24 AS first_score_hours,
    (SELECT s.id FROM submissions s
        WHERE s.user_id = u.id AND s.status = 'in_progress'
          AND (julianday('now') - julianday(s.started_at)) * 24 BETWEEN 48 AND 168
        ORDER BY s.started_at DESC LIMIT 1) AS stalled_submission_id,
    EXISTS (SELECT 1 FROM submissions s WHERE s.user_id = u.id
        AND (julianday(s.started_at) >= julianday('now', '-1 day')
             OR julianday(s.scored_at) >= julianday('now', '-1 day'))) AS recent_activity,
    julianday('now') - (SELECT MAX(MAX(julianday(s.started_at), COALESCE(julianday(s.scored_at), 0)))
        FROM submissions s WHERE s.user_id = u.id) AS inactive_days,
    (SELECT COUNT(*) FROM challenges ch WHERE ch.is_public = 1
        AND julianday(ch.created_at) > (SELECT MAX(julianday(s.started_at)) FROM submissions s
                                        WHERE s.user_id = u.id)) AS new_challenges,
    (SELECT COUNT(*) FROM email_sends e WHERE e.user_id = u.id AND e.stream = 'lifecycle'
        AND e.status IN ('sent', 'claimed') AND julianday(e.created_at) >= julianday('now', '-1 day')) AS sends_24h,
    (SELECT COUNT(*) FROM email_sends e WHERE e.user_id = u.id AND e.stream = 'lifecycle'
        AND e.status IN ('sent', 'claimed') AND julianday(e.created_at) >= julianday('now', '-7 days')) AS sends_7d,
    (SELECT COUNT(*) FROM email_sends e WHERE e.user_id = u.id AND e.template = 'reengage'
        AND e.status IN ('sent', 'claimed')) AS reengage_sent,
    julianday('now') - (SELECT MAX(julianday(e.created_at)) FROM email_sends e
        WHERE e.user_id = u.id AND e.template = 'reengage' AND e.status IN ('sent', 'claimed')) AS last_reengage_days
FROM users u
WHERE {base}
"""


@dataclass(frozen=True)
class LifecycleTemplate:
    template: str
    stream: str
    segment_sql: str
    """WHERE fragment over the _STATE_SQL columns (alias st)."""
    render: Callable[..., RenderedEmail]
    context: Callable[[dict[str, Any], bool], tuple[dict[str, Any] | None, str | None]]
    """(row, preview) -> (render kwargs, None) or (None, skip reason). Preview never skips."""
    reason: Callable[[dict[str, Any]], str]
    dedupe_sql: str
    """SQL expression for the dedupe key; must match dedupe_key()."""
    dedupe_key: Callable[[dict[str, Any]], str]
    verified: bool = True
    milestone: bool = False
    schedulable: bool = True


# ---------------------------------------------------------------------------
# Base filter and state queries
# ---------------------------------------------------------------------------

def _base_where(verified: bool) -> tuple[str, list[Any]]:
    clauses = [
        "u.user_type = 'developer'",
        "u.is_banned = 0",
        "COALESCE(u.is_demo, 0) = 0",
        "lower(u.email) NOT LIKE '%@demo.kodwai.dev'",
        "u.email_unsubscribed_at IS NULL",
        "u.email_suppressed_at IS NULL",
        "u.email_verified = 1" if verified else "u.email_verified = 0",
    ]
    params: list[Any] = []
    internal = settings.internal_emails_list
    if internal:
        clauses.append(f"lower(u.email) NOT IN ({', '.join('?' for _ in internal)})")
        params.extend(internal)
    return " AND ".join(clauses), params


def _not_sent(dedupe_sql: str) -> str:
    """No row for this key, unless it is a failed row that send_tracked may still retry."""
    return (
        f"NOT EXISTS (SELECT 1 FROM email_sends e WHERE e.dedupe_key = ({dedupe_sql}) "
        f"AND NOT (e.status = 'failed' AND e.attempts < {MAX_SEND_ATTEMPTS}))"
    )


def segment_rows(tpl: LifecycleTemplate) -> list[dict[str, Any]]:
    """Users currently in ``tpl``'s segment who have not had its email, oldest signup first."""
    base, params = _base_where(tpl.verified)
    sql = (
        f"SELECT * FROM ({_STATE_SQL.format(base=base)}) st "
        f"WHERE ({tpl.segment_sql}) AND {_not_sent(tpl.dedupe_sql)} "
        "ORDER BY st.created_at ASC, st.user_id ASC"
    )
    return fetch_all(sql, tuple(params))


def _eligible_state(user_id: str, verified: bool = True) -> dict[str, Any] | None:
    """State row for one user if they pass the base filter (event-driven sends)."""
    base, params = _base_where(verified)
    return fetch_one(_STATE_SQL.format(base=f"{base} AND u.id = ?"), (*params, user_id))


def _any_state(user_id: str) -> dict[str, Any] | None:
    """State row for one user with no filter at all (previews, including internal accounts)."""
    return fetch_one(_STATE_SQL.format(base="u.id = ?"), (user_id,))


# ---------------------------------------------------------------------------
# Context builders (DB state -> render kwargs)
# ---------------------------------------------------------------------------

def _common(row: dict[str, Any]) -> dict[str, Any]:
    return {"user_id": row["user_id"], "name": first_name(row.get("name"))}


def _starter() -> dict[str, Any]:
    slug = settings.LIFECYCLE_STARTER_CHALLENGE_SLUG
    ch = fetch_one("SELECT title, time_limit_minutes FROM challenges WHERE slug = ? AND is_public = 1", (slug,))
    return {
        "starter_slug": slug,
        "starter_title": ch["title"] if ch else None,
        "starter_minutes": ch["time_limit_minutes"] if ch else None,
    }


def _axes(breakdown_json: str | None) -> list[dict[str, Any]]:
    try:
        data = json.loads(breakdown_json) if breakdown_json else {}
    except (TypeError, ValueError):
        return []
    axes = data.get("axes") if isinstance(data, dict) else None
    return [a for a in axes or [] if isinstance(a, dict) and (a.get("points") or 0) > 0]


def top_axis(breakdown_json: str | None) -> str | None:
    """Axis with the highest share of its points (e.g. 'direction'), or None."""
    axes = _axes(breakdown_json)
    if not axes:
        return None
    return max(axes, key=lambda a: (a.get("score") or 0) / a["points"]).get("name")


def most_missed_axis(breakdown_json: str | None) -> str | None:
    """Axis where the most points were left on the table, or None."""
    axes = _axes(breakdown_json)
    if not axes:
        return None
    best = max(axes, key=lambda a: a["points"] - (a.get("score") or 0))
    return best.get("name") if best["points"] - (best.get("score") or 0) > 0 else None


def _ctx_verify_reminder(row: dict[str, Any], preview: bool) -> tuple[dict[str, Any] | None, str | None]:
    token = row.get("verification_token")
    if not token:
        if not preview:
            return None, "no_verification_token"
        token = "PREVIEW_TOKEN"
    return {**_common(row), "verify_url": app_url(f"/verify?token={token}")}, None


def _ctx_starter(row: dict[str, Any], preview: bool) -> tuple[dict[str, Any] | None, str | None]:
    return {**_common(row), **_starter()}, None


def _ctx_d1_start(row: dict[str, Any], preview: bool) -> tuple[dict[str, Any] | None, str | None]:
    limit = entitlement_service.free_limit()
    remaining = max(0, limit - entitlement_service.free_submissions_used(row["user_id"]))
    return {**_common(row), **_starter(), "free_remaining": remaining, "free_limit": limit}, None


def _ctx_stalled(row: dict[str, Any], preview: bool) -> tuple[dict[str, Any] | None, str | None]:
    sub = None
    if row.get("stalled_submission_id"):
        sub = fetch_one(
            """SELECT c.slug, c.title, CAST(julianday('now') - julianday(s.started_at) AS INTEGER) AS days_open
               FROM submissions s JOIN challenges c ON s.challenge_id = c.id WHERE s.id = ?""",
            (row["stalled_submission_id"],),
        )
    if sub is None:
        if not preview:
            return None, "no_stalled_submission"
        starter = _starter()
        sub = {"slug": starter["starter_slug"], "title": starter["starter_title"] or "Bookshelf REST API", "days_open": 2}
    return {
        **_common(row),
        "challenge_slug": sub["slug"],
        "challenge_title": sub["title"],
        "days_open": max(2, int(sub["days_open"] or 2)),
    }, None


def _ctx_first_score(row: dict[str, Any], preview: bool) -> tuple[dict[str, Any] | None, str | None]:
    sub = fetch_one(
        """SELECT s.id, s.score, s.share_token, s.score_breakdown, c.title
           FROM submissions s JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'scored' AND s.leaderboard_eligible = 1
           ORDER BY s.scored_at ASC LIMIT 1""",
        (row["user_id"],),
    )
    if sub is None:
        if not preview:
            return None, "no_scored_submission"
        return {**_common(row), "score": 72, "challenge_title": "Bookshelf REST API",
                "result_url": app_url("/dev/submissions"), "top_axis": "direction"}, None
    token = sub["share_token"]
    return {
        **_common(row),
        "score": sub["score"] or 0,
        "challenge_title": sub["title"],
        "result_url": app_url(f"/s/{token}") if token else app_url(f"/dev/submissions/{sub['id']}"),
        "is_share_card": bool(token),
        "top_axis": top_axis(sub["score_breakdown"]),
    }, None


_HARDER = {"easy": ("medium", "hard"), "medium": ("hard",), "hard": ("hard",)}


def _ctx_d7_scored(row: dict[str, Any], preview: bool) -> tuple[dict[str, Any] | None, str | None]:
    best = fetch_one(
        """SELECT s.score, s.score_breakdown, c.title, c.difficulty
           FROM submissions s JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'scored' ORDER BY s.score DESC LIMIT 1""",
        (row["user_id"],),
    )
    harder = None
    if best is not None:
        levels = _HARDER.get((best["difficulty"] or "").lower(), ("medium", "hard"))
        harder = fetch_one(
            f"""SELECT slug, title, difficulty, time_limit_minutes FROM challenges
                WHERE is_public = 1 AND difficulty IN ({', '.join('?' for _ in levels)})
                  AND id NOT IN (SELECT challenge_id FROM submissions WHERE user_id = ?)
                ORDER BY CASE difficulty WHEN ? THEN 0 ELSE 1 END, is_featured DESC,
                         submission_count DESC, created_at ASC, slug ASC
                LIMIT 1""",
            (*levels, row["user_id"], levels[0]),
        )
    if best is None or harder is None:
        if not preview:
            return None, "no_scored_submission" if best is None else "no_harder_challenge"
        best = best or {"score": 72, "score_breakdown": None, "title": "Bookshelf REST API"}
        harder = harder or {"slug": "idempotent-etl-pipeline-with-schema-drift",
                            "title": "Idempotent ETL Pipeline with Schema Drift",
                            "difficulty": "medium", "time_limit_minutes": 90}
    return {
        **_common(row),
        "score": best["score"] or 0,
        "challenge_title": best["title"],
        "most_missed_axis": most_missed_axis(best["score_breakdown"]),
        "harder_slug": harder["slug"],
        "harder_title": harder["title"],
        "harder_difficulty": harder["difficulty"],
        "harder_minutes": harder["time_limit_minutes"],
    }, None


def _ctx_plain(row: dict[str, Any], preview: bool) -> tuple[dict[str, Any] | None, str | None]:
    return _common(row), None


def _ctx_reengage(row: dict[str, Any], preview: bool) -> tuple[dict[str, Any] | None, str | None]:
    newest = fetch_one(
        """SELECT title FROM challenges WHERE is_public = 1 AND julianday(created_at) >
               (SELECT MAX(julianday(started_at)) FROM submissions WHERE user_id = ?)
           ORDER BY created_at DESC, slug ASC LIMIT 1""",
        (row["user_id"],),
    )
    count = int(row.get("new_challenges") or 0)
    if count <= 0 or newest is None:
        if not preview:
            return None, "no_new_challenges"
        return {**_common(row), "new_count": 3, "newest_title": "Raft-Lite Log Replication"}, None
    return {**_common(row), "new_count": count, "newest_title": newest["title"]}, None


def _ctx_news(row: dict[str, Any], preview: bool) -> tuple[dict[str, Any] | None, str | None]:
    if not preview:
        return None, "news_is_manual"
    # A realistic sample so the preview shows the real layout; real news is written per send.
    return {**_common(row),
            "headline": "Every challenge now has its own page",
            "body": ("Quick update from me. You can now browse every kodwai challenge without signing in, "
                     "see what each one asks for, and copy the exact command to start it.\n\n"
                     "A few other things shipped this month:\n\n"
                     "- A page that explains the AI Collaboration Score, axis by axis\n"
                     "- Friendlier onboarding emails (you might be reading one)\n"
                     "- Blog posts that are much easier to read on a phone\n\n"
                     "As always, if something feels off, reply and tell me."),
            "url": f"{settings.LANDING_URL.rstrip('/')}/challenges",
            "link_label": "Browse the challenges"}, None


def _hours(row: dict[str, Any], key: str = "age_hours") -> int:
    return int(row.get(key) or 0)


def _days(row: dict[str, Any], key: str = "age_hours") -> int:
    return int((row.get(key) or 0) // 24)


# ---------------------------------------------------------------------------
# Registry, in priority order: the first template a user matches in a run wins.
# ---------------------------------------------------------------------------

_ACTIVATION_OPEN = "st.scored_count = 0"

TEMPLATES: dict[str, LifecycleTemplate] = {t.template: t for t in (
    LifecycleTemplate(
        template="first_score",
        stream="lifecycle",
        segment_sql="st.first_score_hours IS NOT NULL AND st.first_score_hours <= 72",
        render=email_templates.first_score,
        context=_ctx_first_score,
        reason=lambda r: f"first score {_hours(r, 'first_score_hours')}h ago",
        dedupe_sql="'milestone:first_score:' || st.user_id",
        dedupe_key=lambda r: f"milestone:first_score:{r['user_id']}",
        milestone=True,
    ),
    LifecycleTemplate(
        template="welcome",
        stream="lifecycle",
        segment_sql="st.age_hours <= 72 AND st.submissions_started = 0",
        render=email_templates.welcome,
        context=_ctx_starter,
        reason=lambda r: f"signed up {_hours(r)}h ago, no welcome email yet",
        dedupe_sql="'welcome:' || st.user_id",
        dedupe_key=lambda r: f"welcome:{r['user_id']}",
    ),
    LifecycleTemplate(
        template="verify_reminder",
        stream="transactional",
        segment_sql="st.verification_token IS NOT NULL AND st.age_hours BETWEEN 24 AND 72",
        render=email_templates.verify_reminder,
        context=_ctx_verify_reminder,
        reason=lambda r: f"signed up {_hours(r)}h ago, email not verified",
        dedupe_sql="'verify_reminder:' || st.user_id",
        dedupe_key=lambda r: f"verify_reminder:{r['user_id']}",
        verified=False,
    ),
    LifecycleTemplate(
        template="stalled_submission",
        stream="lifecycle",
        segment_sql=f"st.stalled_submission_id IS NOT NULL AND {_ACTIVATION_OPEN}",
        render=email_templates.stalled_submission,
        context=_ctx_stalled,
        reason=lambda r: "submission in progress for 2 to 7 days, nothing scored",
        dedupe_sql="'stalled_submission:' || st.user_id",
        dedupe_key=lambda r: f"stalled_submission:{r['user_id']}",
    ),
    LifecycleTemplate(
        template="d1_start",
        stream="lifecycle",
        segment_sql=(f"st.age_hours BETWEEN 24 AND 72 AND st.has_cli_login = 0 AND st.submissions_started = 0 "
                     f"AND {_ACTIVATION_OPEN}"),
        render=email_templates.d1_start,
        context=_ctx_d1_start,
        reason=lambda r: f"signed up {_hours(r)}h ago, no CLI login",
        dedupe_sql="'d1_start:' || st.user_id",
        dedupe_key=lambda r: f"d1_start:{r['user_id']}",
    ),
    LifecycleTemplate(
        template="d3_first_submit",
        stream="lifecycle",
        segment_sql=(f"st.age_hours BETWEEN 72 AND 144 AND st.has_cli_login = 1 AND st.submissions_started = 0 "
                     f"AND {_ACTIVATION_OPEN}"),
        render=email_templates.d3_first_submit,
        context=_ctx_starter,
        reason=lambda r: f"signed up {_days(r)}d ago, CLI login but no submission",
        dedupe_sql="'d3_first_submit:' || st.user_id",
        dedupe_key=lambda r: f"d3_first_submit:{r['user_id']}",
    ),
    LifecycleTemplate(
        template="d7_scored",
        stream="lifecycle",
        segment_sql="st.age_hours BETWEEN 168 AND 240 AND st.scored_count >= 1 AND st.submissions_active <= 1",
        render=email_templates.d7_scored,
        context=_ctx_d7_scored,
        reason=lambda r: f"signed up {_days(r)}d ago, scored once, no second submission",
        dedupe_sql="'d7_scored:' || st.user_id",
        dedupe_key=lambda r: f"d7_scored:{r['user_id']}",
    ),
    LifecycleTemplate(
        template="d7_not_scored",
        stream="lifecycle",
        segment_sql=f"st.age_hours BETWEEN 168 AND 240 AND {_ACTIVATION_OPEN}",
        render=email_templates.d7_not_scored,
        context=_ctx_plain,
        reason=lambda r: f"signed up {_days(r)}d ago, nothing scored",
        dedupe_sql="'d7_not_scored:' || st.user_id",
        dedupe_key=lambda r: f"d7_not_scored:{r['user_id']}",
    ),
    LifecycleTemplate(
        template="reengage",
        stream="lifecycle",
        segment_sql=(f"st.scored_count >= 1 AND st.inactive_days >= 30 AND st.new_challenges > 0 "
                     f"AND st.reengage_sent < {REENGAGE_MAX_SENDS} "
                     "AND (st.reengage_sent = 0 OR st.last_reengage_days >= 14)"),
        render=email_templates.reengage,
        context=_ctx_reengage,
        reason=lambda r: (f"inactive {int(r.get('inactive_days') or 0)}d after scoring, "
                          f"{int(r.get('new_challenges') or 0)} new challenges, send {int(r.get('reengage_sent') or 0) + 1}"),
        dedupe_sql="'reengage:' || st.user_id || ':' || (st.reengage_sent + 1)",
        dedupe_key=lambda r: f"reengage:{r['user_id']}:{int(r.get('reengage_sent') or 0) + 1}",
    ),
    # Product news is marketing: consent only (users.marketing_consent_at), written and sent by hand.
    # Registered for previews; the runner never schedules it.
    LifecycleTemplate(
        template="news",
        stream="lifecycle",
        segment_sql="0",
        render=email_templates.news,
        context=_ctx_news,
        reason=lambda r: "manual product news",
        dedupe_sql="'news:' || st.user_id",
        dedupe_key=lambda r: f"news:{r['user_id']}",
        schedulable=False,
    ),
)}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def real_send_refusal() -> str | None:
    """Why real lifecycle sends must not happen right now, or None when they may.

    Same reason strings as send_tracked, so the digest reads one vocabulary."""
    if not flag_active_by_key(LIFECYCLE_FLAG):
        return f"flag_off:{LIFECYCLE_FLAG}"
    if not settings.EMAIL_FROM_LIFECYCLE.strip():
        return "email_from_lifecycle_unset"
    if not settings.EMAIL_REPLY_TO.strip():
        return "reply_to_unset"
    if not settings.RESEND_API_KEY:
        return "resend_not_configured"
    if not settings.UNSUBSCRIBE_SECRET:
        return "unsubscribe_secret_unset"
    return None


def new_run_id() -> str:
    return f"lc-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"


def select_templates(names: list[str] | None) -> list[LifecycleTemplate]:
    """Schedulable templates in priority order, optionally narrowed to ``names``.

    Raises ValueError on an unknown name or a manual-only template (news)."""
    if not names:
        return [t for t in TEMPLATES.values() if t.schedulable]
    unknown = sorted({n for n in names if n not in TEMPLATES})
    if unknown:
        raise ValueError(f"Unknown templates: {', '.join(unknown)}")
    manual = sorted({n for n in names if not TEMPLATES[n].schedulable})
    if manual:
        raise ValueError(f"Not scheduled by the runner: {', '.join(manual)}")
    wanted = set(names)
    return [t for t in TEMPLATES.values() if t.template in wanted]


def _cap_skip(tpl: LifecycleTemplate, row: dict[str, Any]) -> str | None:
    if tpl.milestone:
        return None
    if row.get("recent_activity"):
        return "recent_activity"
    if (row.get("sends_24h") or 0) >= DAILY_CAP:
        return "cap_daily"
    if (row.get("sends_7d") or 0) >= WEEKLY_CAP:
        return "cap_weekly"
    return None


def _item(row: dict[str, Any], template: str, reason: str | None, status: str, **extra: Any) -> dict[str, Any]:
    return {
        "user_id": row["user_id"],
        "masked_email": mask_email(row.get("email")),
        "template": template,
        "reason": reason,
        "status": status,
        "subject": extra.get("subject"),
        "email_send_id": extra.get("email_send_id"),
        "error": extra.get("error"),
    }


def run(
    *,
    dry_run: bool = True,
    limit: int = 50,
    templates: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Plan (dry run) or send one pass of the lifecycle sequence.

    Returns ``{run_id, dry_run, refused_reason, items, counts, limit_reached}``. Item status is
    send_tracked's (sent, failed, duplicate, skipped, dry_run), 'skipped' for a runner rule
    (recent_activity, cap_daily, cap_weekly, or a missing-data reason), or 'refused' when a real
    run was refused. ``limit`` caps the emails planned or attempted, not the skips listed.
    Running it twice sends nothing twice: segments exclude sent keys and send_tracked claims them.
    """
    run_id = run_id or new_run_id()
    selected = select_templates(templates)
    refused_reason = None if dry_run else real_send_refusal()
    plan_only = dry_run or refused_reason is not None

    items: list[dict[str, Any]] = []
    handled: set[str] = set()
    attempts = 0
    limit_reached = False

    for tpl in selected:
        if limit_reached:
            break
        for row in segment_rows(tpl):
            uid = row["user_id"]
            if uid in handled:
                continue
            if attempts >= limit:
                limit_reached = True
                break
            skip = _cap_skip(tpl, row)
            if skip:
                # Caps and the activity rule apply to every non-milestone template alike.
                handled.add(uid)
                items.append(_item(row, tpl.template, skip, "skipped"))
                continue
            ctx, why_not = tpl.context(row, False)
            if ctx is None:
                items.append(_item(row, tpl.template, why_not, "skipped"))
                continue
            reason = tpl.reason(row)
            email = tpl.render(**ctx)
            result = send_tracked(
                uid, row["email"], tpl.template, email.subject, email.html, email.text, tpl.stream,
                tpl.dedupe_key(row), run_id=run_id, dry_run=plan_only, meta={"reason": reason, "trigger": "runner"},
            )
            status = result["status"]
            if refused_reason and status == "dry_run":
                status = "refused"
            items.append(_item(
                row, tpl.template, result.get("reason") if status in ("skipped", "duplicate") else reason, status,
                subject=email.subject, email_send_id=result.get("email_send_id"), error=result.get("error"),
            ))
            if status in _SENT_LIKE:
                handled.add(uid)
                attempts += 1

    counts = Counter(item["status"] for item in items)
    if not plan_only:
        logger.info("Lifecycle run %s: %s", run_id, dict(counts))
    return {
        "run_id": run_id,
        "dry_run": dry_run,
        "refused_reason": refused_reason,
        "items": items,
        "counts": dict(counts),
        "limit_reached": limit_reached,
    }


_SAMPLE_ROW: dict[str, Any] = {
    "user_id": "preview-user", "email": "dev@example.com", "name": "Ada Lovelace", "age_hours": 30,
    "verification_token": None, "stalled_submission_id": None, "new_challenges": 0, "reengage_sent": 0,
}


def preview(template: str, user_id: str | None = None) -> dict[str, str]:
    """Render ``template`` for a real user (any account, no filters) or a sample user.

    Raises ValueError for an unknown template and LookupError for an unknown user."""
    tpl = TEMPLATES.get(template)
    if tpl is None:
        raise ValueError(f"Unknown template: {template}")
    if user_id:
        row = _any_state(user_id)
        if row is None:
            raise LookupError("User not found")
    else:
        row = dict(_SAMPLE_ROW)
    ctx, _ = tpl.context(row, True)
    email = tpl.render(**(ctx or {}))
    return {"template": template, "subject": email.subject, "text": email.text, "html": email.html}


def list_email_sends(since: str | None = None, template: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """The send ledger, newest first, with masked recipients. ``since`` is YYYY-MM-DD (UTC)."""
    clauses: list[str] = []
    params: list[Any] = []
    if since:
        clauses.append("date(created_at) >= date(?)")
        params.append(since)
    if template:
        clauses.append("template = ?")
        params.append(template)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = fetch_all(
        f"""SELECT id, user_id, to_email, template, stream, status, created_at, sent_at, error
            FROM email_sends {where} ORDER BY created_at DESC, id DESC LIMIT ?""",
        (*params, limit),
    )
    return [
        {
            "id": r["id"],
            "user_id": r["user_id"],
            "masked_email": mask_email(r["to_email"]),
            "template": r["template"],
            "stream": r["stream"],
            "status": r["status"],
            "created_at": r["created_at"],
            "sent_at": r["sent_at"],
            "error": r["error"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Event-driven sends (welcome on verify / new GitHub account, first score)
# ---------------------------------------------------------------------------

def _spawn(fn: Callable[..., Any], *args: Any) -> None:
    """Run ``fn`` in a daemon thread so request paths never wait on Resend. Tests patch this."""
    def _run() -> None:
        try:
            fn(*args)
        except Exception:
            logger.exception("Background lifecycle send failed")
    threading.Thread(target=_run, daemon=True).start()


def send_event_email(template: str, user_id: str) -> dict[str, Any] | None:
    """Render and send one event-driven lifecycle email now (synchronous).

    Returns send_tracked's result, or None when the user fails the base filter (company account,
    demo, internal, banned, unsubscribed, suppressed, unverified) or the context is missing.
    send_tracked re-checks the flag and dedupes on the same key the daily backstop uses."""
    tpl = TEMPLATES[template]
    row = _eligible_state(user_id, tpl.verified)
    if row is None:
        return None
    ctx, why_not = tpl.context(row, False)
    if ctx is None:
        logger.info("Skipping %s for %s: %s", template, user_id, why_not)
        return None
    email = tpl.render(**ctx)
    return send_tracked(
        user_id, row["email"], template, email.subject, email.html, email.text, tpl.stream,
        tpl.dedupe_key(row), meta={"trigger": "event"},
    )


def trigger_welcome(user_id: str) -> None:
    """Welcome email after email verification or a new GitHub signup. Never raises.

    A no-op unless real lifecycle sends are allowed (flag on, sender config set), so deploying
    this changes nothing until the founder flips lifecycle_emails. The send runs off-request."""
    try:
        if real_send_refusal() is not None:
            return
        _spawn(send_event_email, "welcome", user_id)
    except Exception:
        logger.exception("Could not queue the welcome email for %s", user_id)


def on_submission_scored(user_id: str, leaderboard_eligible: bool) -> None:
    """first_score milestone, called by the scoring engine (already off-request). Never raises.

    Fires only for the user's first leaderboard-eligible scored submission, so a scoring error
    (partial score, no AI judgment) never produces a celebration email."""
    try:
        if not leaderboard_eligible or real_send_refusal() is not None:
            return
        row = fetch_one(
            "SELECT COUNT(*) AS n FROM submissions WHERE user_id = ? AND status = 'scored' AND leaderboard_eligible = 1",
            (user_id,),
        )
        if not row or row["n"] != 1:
            return
        send_event_email("first_score", user_id)
    except Exception:
        logger.exception("first_score milestone failed for %s", user_id)
