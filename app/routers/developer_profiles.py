from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import CurrentUser
from app.services.feature_flags import require_flag
from app.services.tiers import tier_for

router = APIRouter(tags=["developers"])


def pick_favorite(rows: list[dict], key_field: str) -> str | None:
    """Highest-count non-empty value of key_field across pre-aggregated rows [{key_field, count}]."""
    best, best_count = None, 0
    for r in rows:
        k = r.get(key_field)
        c = int(r.get("count") or 0)
        if k and c > best_count:
            best, best_count = k, c
    return best


@router.get("/developers/me")
def get_my_profile(current_user: CurrentUser) -> dict:
    """Get current developer's profile."""
    if current_user.get("user_type") != "developer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account required")

    profile = fetch_one(
        """SELECT dp.*, u.name, u.username, u.email
           FROM developer_profiles dp
           JOIN users u ON dp.user_id = u.id
           WHERE dp.user_id = ?""",
        (current_user["id"],),
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    profile["skills"] = json.loads(profile["skills"]) if profile.get("skills") else []

    # Include recent submissions
    submissions = fetch_all(
        """SELECT s.id, s.score, s.agent_used, s.model_display, s.time_taken_ms, s.scored_at,
                  c.title as challenge_title, c.slug as challenge_slug, c.difficulty
           FROM submissions s
           JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'scored'
           ORDER BY s.scored_at DESC LIMIT 10""",
        (current_user["id"],),
    )
    profile["recent_submissions"] = submissions

    profile["tier"] = tier_for(profile.get("direction_rating"))

    return profile


class ProfileUpdateRequest(BaseModel):
    bio: Optional[str] = None
    github_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    website_url: Optional[str] = None
    x_url: Optional[str] = None
    skills: Optional[list[str]] = None
    preferred_agent: Optional[str] = None


@router.put("/developers/me")
def update_my_profile(body: ProfileUpdateRequest, current_user: CurrentUser) -> dict:
    """Update current developer's profile."""
    if current_user.get("user_type") != "developer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account required")

    updates: list[str] = []
    params: list = []

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "skills" and value is not None:
            value = json.dumps(value)
        updates.append(f"{field} = ?")
        params.append(value)

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(current_user["id"])
        execute(f"UPDATE developer_profiles SET {', '.join(updates)} WHERE user_id = ?", tuple(params))

    return get_my_profile(current_user)


@router.get("/developers/me/skills")
def my_skills(current_user: CurrentUser) -> dict:
    """Per-category and per-model mastery ratings (ELO) for the current developer."""
    if current_user.get("user_type") != "developer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account required")
    rows = fetch_all(
        "SELECT dimension, key, rating FROM user_skill_ratings WHERE user_id = ? ORDER BY rating DESC",
        (current_user["id"],),
    )
    return {
        "category": [{"key": r["key"], "rating": r["rating"]} for r in rows if r["dimension"] == "category"],
        "model": [{"key": r["key"], "rating": r["rating"]} for r in rows if r["dimension"] == "model"],
    }


@router.get("/developers/me/wrapped", dependencies=[require_flag("wrapped")])
def my_wrapped(current_user: CurrentUser) -> dict:
    """Aggregated 'kodwai Wrapped' recap of the current developer's stats."""
    if current_user.get("user_type") != "developer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account required")
    uid = current_user["id"]
    profile = fetch_one(
        "SELECT total_score, challenges_completed, rank, streak_days, direction_rating "
        "FROM developer_profiles WHERE user_id = ?",
        (uid,),
    ) or {}
    agg = fetch_one(
        "SELECT COUNT(*) AS submissions, MAX(score) AS best_score "
        "FROM submissions WHERE user_id = ? AND status = 'scored'",
        (uid,),
    ) or {}
    agents = fetch_all(
        "SELECT agent_used, COUNT(*) AS count FROM submissions "
        "WHERE user_id = ? AND status = 'scored' AND agent_used IS NOT NULL GROUP BY agent_used",
        (uid,),
    )
    models = fetch_all(
        "SELECT model_display, COUNT(*) AS count FROM submissions "
        "WHERE user_id = ? AND status = 'scored' AND model_display IS NOT NULL GROUP BY model_display",
        (uid,),
    )
    top_cat = fetch_one(
        "SELECT key, rating FROM user_skill_ratings "
        "WHERE user_id = ? AND dimension = 'category' ORDER BY rating DESC LIMIT 1",
        (uid,),
    )
    badges = fetch_one("SELECT COUNT(*) AS c FROM developer_badges WHERE user_id = ?", (uid,)) or {}
    user = fetch_one("SELECT created_at, name, username FROM users WHERE id = ?", (uid,)) or {}
    return {
        "name": user.get("name"),
        "username": user.get("username"),
        "member_since": user.get("created_at"),
        "challenges_completed": profile.get("challenges_completed") or 0,
        "submissions": agg.get("submissions") or 0,
        "best_score": agg.get("best_score"),
        "direction_rating": profile.get("direction_rating") or 1000,
        "streak_days": profile.get("streak_days") or 0,
        "rank": profile.get("rank"),
        "badges_count": badges.get("c") or 0,
        "favorite_agent": pick_favorite([dict(a) for a in agents], "agent_used"),
        "favorite_model": pick_favorite([dict(m) for m in models], "model_display"),
        "top_category": ({"key": top_cat["key"], "rating": top_cat["rating"]} if top_cat else None),
    }


@router.get("/developers/{username}")
def get_public_profile(username: str) -> dict:
    """Get a developer's public profile."""
    profile = fetch_one(
        """SELECT dp.*, u.name, u.username
           FROM developer_profiles dp
           JOIN users u ON dp.user_id = u.id
           WHERE u.username = ?""",
        (username,),
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found")

    profile["skills"] = json.loads(profile["skills"]) if profile.get("skills") else []

    # Get recent submissions (public)
    submissions = fetch_all(
        """SELECT s.id, s.score, s.agent_used, s.model_display, s.time_taken_ms, s.scored_at,
                  c.title as challenge_title, c.slug as challenge_slug, c.difficulty
           FROM submissions s
           JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'scored'
           ORDER BY s.scored_at DESC LIMIT 10""",
        (profile["user_id"],),
    )

    profile["recent_submissions"] = submissions

    # Get earned badges
    badges = fetch_all(
        """SELECT b.id, b.name, b.slug, b.description, b.icon, b.category, db.earned_at
           FROM developer_badges db
           JOIN badges b ON db.badge_id = b.id
           WHERE db.user_id = ?
           ORDER BY db.earned_at DESC""",
        (profile["user_id"],),
    )
    profile["badges"] = badges

    profile["tier"] = tier_for(profile.get("direction_rating"))

    return profile


@router.get("/developers/{username}/submissions")
def get_developer_submissions(username: str) -> list[dict]:
    """Get a developer's public submission history."""
    user = fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found")

    rows = fetch_all(
        """SELECT s.id, s.score, s.agent_used, s.model_display, s.time_taken_ms, s.scored_at,
                  c.title as challenge_title, c.slug as challenge_slug, c.difficulty
           FROM submissions s
           JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'scored'
           ORDER BY s.scored_at DESC""",
        (user["id"],),
    )
    return rows
