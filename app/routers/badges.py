from __future__ import annotations

import json

from fastapi import APIRouter

from app.core.database import fetch_all, fetch_one
from app.core.deps import CurrentUser

router = APIRouter(prefix="/badges", tags=["badges"])


@router.get("")
def list_badges() -> list[dict]:
    """List all badge definitions with earned counts."""
    badges = fetch_all(
        """SELECT b.*,
                  (SELECT COUNT(*) FROM developer_badges db WHERE db.badge_id = b.id) as earned_count,
                  (SELECT COUNT(*) FROM developer_profiles WHERE challenges_completed > 0) as total_developers
           FROM badges b
           WHERE b.is_active = 1
           ORDER BY b.category, b.name""",
    )
    for b in badges:
        b["criteria"] = json.loads(b["criteria"]) if b.get("criteria") else {}
        total = b.pop("total_developers", 1) or 1
        b["earned_percentage"] = round((b["earned_count"] / total) * 100, 1) if b["earned_count"] else 0
    return badges


@router.get("/progress")
def badge_progress_me(current_user: CurrentUser) -> list[dict]:
    """All badges with earned state + progress toward unearned countable ones."""
    from app.services.badge_engine import _get_user_stats, badge_progress
    badges = fetch_all("SELECT id, name, slug, description, icon, category, criteria FROM badges WHERE is_active = 1 ORDER BY category, name")
    earned = {r["badge_id"] for r in fetch_all("SELECT badge_id FROM developer_badges WHERE user_id = ?", (current_user["id"],))}
    stats = _get_user_stats(current_user["id"])
    out = []
    for b in badges:
        crit = json.loads(b["criteria"]) if b.get("criteria") else {}
        prog = badge_progress(crit, stats)
        out.append({
            "slug": b["slug"], "name": b["name"], "description": b["description"],
            "icon": b["icon"], "category": b["category"],
            "earned": b["id"] in earned,
            "progressable": prog["progressable"], "current": prog["current"], "target": prog["target"],
        })
    return out


@router.get("/me")
def my_badges(current_user: CurrentUser) -> list[dict]:
    """List current developer's earned badges."""
    rows = fetch_all(
        """SELECT b.id, b.name, b.slug, b.description, b.icon, b.category, db.earned_at
           FROM developer_badges db
           JOIN badges b ON db.badge_id = b.id
           WHERE db.user_id = ?
           ORDER BY db.earned_at DESC""",
        (current_user["id"],),
    )
    return rows
