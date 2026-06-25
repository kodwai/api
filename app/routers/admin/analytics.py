from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.admin_deps import AdminUser
from app.core.database import fetch_all

router = APIRouter(tags=["admin-analytics"])


@router.get("/analytics/signups")
def signup_analytics(current_admin: AdminUser, days: int = Query(30, ge=1, le=365)) -> list[dict]:
    """Daily signup counts."""
    return fetch_all(
        "SELECT date(created_at) as date, COUNT(*) as count FROM users WHERE created_at >= datetime('now', '-' || ? || ' days') GROUP BY date(created_at) ORDER BY date",
        (days,),
    )


@router.get("/analytics/submissions")
def submission_analytics(current_admin: AdminUser, days: int = Query(30, ge=1, le=365)) -> list[dict]:
    """Daily submission counts."""
    return fetch_all(
        "SELECT date(created_at) as date, COUNT(*) as count FROM submissions WHERE created_at >= datetime('now', '-' || ? || ' days') GROUP BY date(created_at) ORDER BY date",
        (days,),
    )


@router.get("/analytics/sessions")
def session_analytics(current_admin: AdminUser, days: int = Query(30, ge=1, le=365)) -> list[dict]:
    """Daily session counts."""
    return fetch_all(
        "SELECT date(created_at) as date, COUNT(*) as count FROM sessions WHERE created_at >= datetime('now', '-' || ? || ' days') GROUP BY date(created_at) ORDER BY date",
        (days,),
    )


@router.get("/analytics/agents")
def agent_analytics(current_admin: AdminUser) -> list[dict]:
    """Agent usage distribution."""
    return fetch_all(
        "SELECT agent_used, COUNT(*) as count FROM submissions WHERE agent_used IS NOT NULL AND status = 'scored' GROUP BY agent_used ORDER BY count DESC",
    )


@router.get("/analytics/challenges")
def challenge_analytics(current_admin: AdminUser) -> list[dict]:
    """Top challenges by submission count."""
    return fetch_all(
        "SELECT c.title, c.slug, c.difficulty, c.submission_count, c.avg_score FROM challenges c WHERE c.submission_count > 0 ORDER BY c.submission_count DESC LIMIT 20",
    )


@router.get("/analytics/scores")
def score_analytics(current_admin: AdminUser) -> list[dict]:
    """Score distribution histogram."""
    buckets = [
        ("0-20", 0, 20), ("20-40", 20, 40), ("40-60", 40, 60),
        ("60-80", 60, 80), ("80-100", 80, 100),
    ]
    result = []
    for label, low, high in buckets:
        row = fetch_all(
            "SELECT COUNT(*) as count FROM submissions WHERE status = 'scored' AND score >= ? AND score < ?",
            (low, high if high < 100 else 101),
        )
        result.append({"bucket": label, "count": row[0]["count"] if row else 0})
    return result
