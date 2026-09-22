"""Growth baseline stats for the daily routine (mounted under /api/admin).

Routes:
  GET /growth/baseline   scope stats:read

Every user-level number counts real users only: demo accounts (users.is_demo or an
@demo.kodwai.dev email), superadmins and INTERNAL_EMAILS are excluded. The older
/api/admin/analytics/* endpoints include demo users and count in_progress rows, so the
routine reads this instead.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.automation_deps import require_scope
from app.core.config import settings
from app.core.database import fetch_all, fetch_one
from app.services.email_service import mask_email

router = APIRouter(tags=["admin-growth"])

StatsReader = Annotated[dict[str, Any], Depends(require_scope("stats:read"))]

DEFAULT_WINDOW_DAYS = 7
MAX_NEW_USERS = 500
# Activation ladder, lowest to highest. A user's state is the highest step reached (ever).
ACTIVATION_STATES: tuple[str, ...] = ("signed_up", "cli_login", "submission_started", "scored")


def _real_users(alias: str = "u") -> tuple[str, list[Any]]:
    """SQL condition (and params) keeping real users only."""
    clause = (
        f"{alias}.is_demo = 0 AND lower({alias}.email) NOT LIKE ? AND {alias}.is_superadmin = 0"
    )
    params: list[Any] = ["%@demo.kodwai.dev"]
    internal = settings.internal_emails_list
    if internal:
        clause += f" AND lower({alias}.email) NOT IN ({', '.join('?' for _ in internal)})"
        params.extend(internal)
    return clause, params


def _count(query: str, params: list[Any]) -> int:
    row = fetch_one(query, tuple(params))
    return int(row["n"] or 0) if row else 0


@router.get("/growth/baseline")
def growth_baseline(
    principal: StatsReader,
    since: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
) -> dict:
    """Demo- and internal-filtered funnel counts since ``since`` (UTC date, default 7 days ago).

    cli_logins: distinct real users who completed a CLI browser login (a used cli_auth_code).
    submissions.started / scored: rows started, and rows scored, inside the window.
    new_users: users created in the window with their highest activation state.
    email_sends: tracked sends created in the window by template and status (all recipients).
    resend_sends_today: tracked sends marked sent today (UTC). Untracked auth mail is not counted.
    real_scored_submissions_total: all-time scored submissions by real users.
    """
    now = datetime.now(timezone.utc)
    if since is None:
        since = (now.date() - timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()
    else:
        try:
            date.fromisoformat(since)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="since must be YYYY-MM-DD") from e
    today = now.date().isoformat()
    real, real_params = _real_users()

    users = fetch_all(
        f"""SELECT u.id, u.email, u.user_type, u.email_verified, u.created_at,
                   CASE WHEN u.github_id IS NOT NULL AND u.github_id != '' THEN 'github' ELSE 'email' END AS method,
                   EXISTS (SELECT 1 FROM cli_auth_codes c WHERE c.user_id = u.id AND c.used_at IS NOT NULL) AS cli_login,
                   EXISTS (SELECT 1 FROM submissions s WHERE s.user_id = u.id) AS submission_started,
                   EXISTS (SELECT 1 FROM submissions s WHERE s.user_id = u.id AND s.status = 'scored') AS scored
            FROM users u
            WHERE {real} AND u.created_at >= ?
            ORDER BY u.created_at DESC""",
        (*real_params, since),
    )

    by_method = {"github": 0, "email": 0}
    by_type: dict[str, int] = {}
    by_state = {state: 0 for state in ACTIVATION_STATES}
    new_users: list[dict[str, Any]] = []
    for u in users:
        by_method[u["method"]] = by_method.get(u["method"], 0) + 1
        by_type[u["user_type"]] = by_type.get(u["user_type"], 0) + 1
        state = "signed_up"
        for step in ACTIVATION_STATES[1:]:
            if u[step]:
                state = step
        by_state[state] += 1
        new_users.append({
            "user_id": u["id"],
            "masked_email": mask_email(u["email"]),
            "method": u["method"],
            "user_type": u["user_type"],
            "email_verified": bool(u["email_verified"]),
            "created_at": u["created_at"],
            "state": state,
        })

    cli_logins = _count(
        f"""SELECT COUNT(DISTINCT c.user_id) AS n
            FROM cli_auth_codes c JOIN users u ON u.id = c.user_id
            WHERE {real} AND c.used_at IS NOT NULL AND c.used_at >= ?""",
        [*real_params, since],
    )
    started = fetch_one(
        f"""SELECT COUNT(*) AS n, COUNT(DISTINCT s.user_id) AS users
            FROM submissions s JOIN users u ON u.id = s.user_id
            WHERE {real} AND s.started_at >= ?""",
        (*real_params, since),
    ) or {}
    scored = fetch_one(
        f"""SELECT COUNT(*) AS n, COUNT(DISTINCT s.user_id) AS users
            FROM submissions s JOIN users u ON u.id = s.user_id
            WHERE {real} AND s.status = 'scored' AND s.scored_at >= ?""",
        (*real_params, since),
    ) or {}
    scored_total = fetch_one(
        f"""SELECT COUNT(*) AS n, COUNT(DISTINCT s.user_id) AS users
            FROM submissions s JOIN users u ON u.id = s.user_id
            WHERE {real} AND s.status = 'scored'""",
        tuple(real_params),
    ) or {}

    platform_feedback = _count(
        f"""SELECT COUNT(*) AS n FROM platform_feedback f JOIN users u ON u.id = f.user_id
            WHERE {real} AND f.created_at >= ?""",
        [*real_params, since],
    )
    challenge_feedback = _count(
        f"""SELECT COUNT(*) AS n FROM challenge_feedback f JOIN users u ON u.id = f.user_id
            WHERE {real} AND f.created_at >= ?""",
        [*real_params, since],
    )

    by_template_status: dict[str, dict[str, int]] = {}
    for r in fetch_all(
        "SELECT template, status, COUNT(*) AS n FROM email_sends WHERE created_at >= ? GROUP BY template, status",
        (since,),
    ):
        by_template_status.setdefault(r["template"], {})[r["status"]] = int(r["n"])
    sends_today = _count(
        "SELECT COUNT(*) AS n FROM email_sends WHERE status = 'sent' AND substr(sent_at, 1, 10) = ?",
        [today],
    )

    return {
        "since": since,
        "generated_at": now.isoformat(timespec="seconds"),
        "signups": {"total": len(users), "by_method": by_method, "by_type": by_type, "by_state": by_state},
        "cli_logins": cli_logins,
        "submissions": {
            "started": int(started.get("n") or 0),
            "started_users": int(started.get("users") or 0),
            "scored": int(scored.get("n") or 0),
            "scored_users": int(scored.get("users") or 0),
        },
        "new_users": new_users[:MAX_NEW_USERS],
        "new_users_truncated": len(new_users) > MAX_NEW_USERS,
        "feedback": {
            "new": platform_feedback + challenge_feedback,
            "platform": platform_feedback,
            "challenge": challenge_feedback,
        },
        "email_sends": {"by_template_status": by_template_status},
        "resend_sends_today": sends_today,
        "real_scored_submissions_total": int(scored_total.get("n") or 0),
        "real_scored_users_total": int(scored_total.get("users") or 0),
    }
