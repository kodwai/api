from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import CurrentUser

router = APIRouter(tags=["developers"])


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
        """SELECT s.id, s.score, s.agent_used, s.time_taken_ms, s.scored_at,
                  c.title as challenge_title, c.slug as challenge_slug, c.difficulty
           FROM submissions s
           JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'scored'
           ORDER BY s.scored_at DESC LIMIT 10""",
        (current_user["id"],),
    )
    profile["recent_submissions"] = submissions

    return profile


class ProfileUpdateRequest(BaseModel):
    bio: Optional[str] = None
    github_url: Optional[str] = None
    linkedin_url: Optional[str] = None
    website_url: Optional[str] = None
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
        """SELECT s.id, s.score, s.agent_used, s.time_taken_ms, s.scored_at,
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

    return profile


@router.get("/developers/{username}/submissions")
def get_developer_submissions(username: str) -> list[dict]:
    """Get a developer's public submission history."""
    user = fetch_one("SELECT id FROM users WHERE username = ?", (username,))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer not found")

    rows = fetch_all(
        """SELECT s.id, s.score, s.agent_used, s.time_taken_ms, s.scored_at,
                  c.title as challenge_title, c.slug as challenge_slug, c.difficulty
           FROM submissions s
           JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'scored'
           ORDER BY s.scored_at DESC""",
        (user["id"],),
    )
    return rows
