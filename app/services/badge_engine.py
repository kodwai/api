"""Badge evaluation engine. Called after each scored submission."""
from __future__ import annotations

import json
import logging
import secrets

from app.core.database import execute, fetch_all, fetch_one

logger = logging.getLogger(__name__)


def evaluate_badges(user_id: str, submission_id: str) -> list[dict]:
    """Check all badge criteria for a user and award any newly earned badges.

    Returns list of newly awarded badge dicts.
    """
    newly_earned: list[dict] = []

    # Fetch all active badges the user hasn't earned yet
    badges = fetch_all(
        """SELECT b.* FROM badges b
           WHERE b.is_active = 1
             AND b.id NOT IN (SELECT badge_id FROM developer_badges WHERE user_id = ?)""",
        (user_id,),
    )

    if not badges:
        return newly_earned

    # Gather user stats once
    stats = _get_user_stats(user_id)

    for badge in badges:
        criteria = json.loads(badge["criteria"]) if badge.get("criteria") else {}
        earned = _check_criteria(criteria, stats, user_id, submission_id)

        if earned:
            _award_badge(user_id, badge["id"], submission_id)
            newly_earned.append({"id": badge["id"], "name": badge["name"], "slug": badge["slug"], "description": badge["description"], "icon": badge["icon"]})
            logger.info("Awarded badge '%s' to user %s", badge["slug"], user_id)

    return newly_earned


def _get_user_stats(user_id: str) -> dict:
    """Gather all stats needed for badge evaluation."""
    profile = fetch_one(
        "SELECT * FROM developer_profiles WHERE user_id = ?",
        (user_id,),
    )

    # Count distinct categories completed
    categories = fetch_all(
        """SELECT DISTINCT c.category FROM submissions s
           JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'scored'""",
        (user_id,),
    )

    # Count agent-specific high scores
    agent_scores = fetch_all(
        """SELECT agent_used, COUNT(*) as count FROM submissions
           WHERE user_id = ? AND status = 'scored' AND score >= 80
           GROUP BY agent_used""",
        (user_id,),
    )

    # Get best score and time ratio for the latest submission
    latest = fetch_one(
        """SELECT s.score, s.time_taken_ms, c.time_limit_minutes
           FROM submissions s JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'scored'
           ORDER BY s.scored_at DESC LIMIT 1""",
        (user_id,),
    )

    # Check percentile for latest submission
    percentile_rank = None
    if latest:
        latest_sub = fetch_one(
            """SELECT s.challenge_id, s.score FROM submissions s
               WHERE s.user_id = ? AND s.status = 'scored'
               ORDER BY s.scored_at DESC LIMIT 1""",
            (user_id,),
        )
        if latest_sub:
            total_for_challenge = fetch_one(
                "SELECT COUNT(*) as count FROM submissions WHERE challenge_id = ? AND status = 'scored'",
                (latest_sub["challenge_id"],),
            )
            better_count = fetch_one(
                "SELECT COUNT(*) as count FROM submissions WHERE challenge_id = ? AND status = 'scored' AND score > ?",
                (latest_sub["challenge_id"], latest_sub["score"]),
            )
            if total_for_challenge and total_for_challenge["count"] >= 5:
                percentile_rank = ((better_count["count"] if better_count else 0) / total_for_challenge["count"]) * 100

    # Check user creation date for early adopter
    user = fetch_one("SELECT created_at FROM users WHERE id = ?", (user_id,))

    return {
        "challenges_completed": profile["challenges_completed"] if profile else 0,
        "streak_days": profile["streak_days"] if profile else 0,
        "total_score": profile["total_score"] if profile else 0,
        "categories_count": len(categories),
        "agent_scores": {row["agent_used"]: row["count"] for row in agent_scores},
        "latest_score": latest["score"] if latest else None,
        "latest_time_ratio": (latest["time_taken_ms"] / (latest["time_limit_minutes"] * 60000)) if latest and latest["time_taken_ms"] and latest["time_limit_minutes"] else None,
        "percentile_rank": percentile_rank,
        "user_created_at": user["created_at"] if user else None,
    }


def badge_progress(criteria: dict, stats: dict) -> dict:
    """Map a badge's criteria + user stats to {progressable, current, target}.
    Only count-based criteria are progressable; others -> progressable False."""
    ctype = criteria.get("type")
    if ctype == "challenges_completed":
        return {"progressable": True, "current": int(stats.get("challenges_completed") or 0), "target": int(criteria.get("min", 1))}
    if ctype == "streak":
        return {"progressable": True, "current": int(stats.get("streak_days") or 0), "target": int(criteria.get("min", 3))}
    if ctype == "categories":
        return {"progressable": True, "current": int(stats.get("categories_count") or 0), "target": int(criteria.get("min", 3))}
    if ctype == "agent_score":
        agent = criteria.get("agent", "")
        return {"progressable": True, "current": int((stats.get("agent_scores") or {}).get(agent, 0)), "target": int(criteria.get("min_count", 5))}
    return {"progressable": False, "current": 0, "target": 0}


def _check_criteria(criteria: dict, stats: dict, user_id: str, submission_id: str) -> bool:
    """Check if a badge's criteria are met."""
    ctype = criteria.get("type")

    if ctype == "challenges_completed":
        return stats["challenges_completed"] >= criteria.get("min", 1)

    elif ctype == "streak":
        return stats["streak_days"] >= criteria.get("min", 3)

    elif ctype == "percentile":
        if stats["percentile_rank"] is None:
            return False
        # percentile_rank is % of people who scored HIGHER, so lower is better
        return stats["percentile_rank"] <= criteria.get("max_percentile", 10)

    elif ctype == "speed":
        if stats["latest_time_ratio"] is None:
            return False
        return stats["latest_time_ratio"] <= criteria.get("max_ratio", 0.5)

    elif ctype == "min_score":
        if stats["latest_score"] is None:
            return False
        return stats["latest_score"] >= criteria.get("min", 95)

    elif ctype == "categories":
        return stats["categories_count"] >= criteria.get("min", 3)

    elif ctype == "agent_score":
        agent = criteria.get("agent", "")
        min_count = criteria.get("min_count", 5)
        count = stats["agent_scores"].get(agent, 0)
        return count >= min_count

    elif ctype == "early_adopter":
        # Check if user signed up within first N days of platform launch
        # For now, always award to existing users (launch period)
        return True

    return False


def _award_badge(user_id: str, badge_id: str, submission_id: str | None) -> None:
    """Insert a developer_badges record."""
    db_id = secrets.token_hex(16)
    execute(
        "INSERT OR IGNORE INTO developer_badges (id, user_id, badge_id, submission_id) VALUES (?, ?, ?, ?)",
        (db_id, user_id, badge_id, submission_id),
    )
