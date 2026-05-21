from __future__ import annotations

from fastapi import APIRouter

from app.core.admin_deps import AdminUser
from app.core.database import fetch_one

router = APIRouter(tags=["admin-dashboard"])


@router.get("/stats")
def admin_stats(current_admin: AdminUser) -> dict:
    """Overview stats for the admin dashboard."""

    users = fetch_one("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN user_type = 'developer' THEN 1 ELSE 0 END) as developers,
            SUM(CASE WHEN user_type = 'company' THEN 1 ELSE 0 END) as companies,
            SUM(CASE WHEN email_verified = 1 THEN 1 ELSE 0 END) as verified,
            SUM(CASE WHEN is_banned = 1 THEN 1 ELSE 0 END) as banned,
            SUM(CASE WHEN date(created_at) = date('now') THEN 1 ELSE 0 END) as signups_today
        FROM users
    """)

    challenges = fetch_one("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN is_public = 1 THEN 1 ELSE 0 END) as published,
            SUM(CASE WHEN is_featured = 1 THEN 1 ELSE 0 END) as featured
        FROM challenges
    """)

    submissions = fetch_one("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'scored' THEN 1 ELSE 0 END) as scored,
            SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
            SUM(CASE WHEN date(created_at) = date('now') THEN 1 ELSE 0 END) as today
        FROM submissions
    """)

    sessions = fetch_one("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN status = 'expired' THEN 1 ELSE 0 END) as expired
        FROM sessions
    """)

    orgs = fetch_one("SELECT COUNT(*) as total FROM organizations")

    return {
        "users": users,
        "challenges": challenges,
        "submissions": submissions,
        "sessions": sessions,
        "organizations": {"total": orgs["total"] if orgs else 0},
    }
