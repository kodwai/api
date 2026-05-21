from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.core.database import fetch_all, fetch_one
from app.core.deps import CurrentUser

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("")
def global_leaderboard(
    agent: Optional[str] = None,
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    """Global leaderboard. Filterable by agent and/or category.

    When agent is set, scores are computed only from submissions using that agent.
    When category is set, scores are computed only from challenges in that category.
    """
    offset = (page - 1) * limit

    # Build the score subquery based on filters (uses alias "sub" for submissions)
    sub_conditions = ["sub.status = 'scored'", "sub.score IS NOT NULL"]
    sub_params: list = []

    if agent:
        sub_conditions.append("sub.agent_used = ?")
        sub_params.append(agent)
    if category:
        sub_conditions.append("c.category = ?")
        sub_params.append(category)

    sub_where = " AND ".join(sub_conditions)

    # Compute weighted avg score per user, filtered by agent/category
    rows = fetch_all(
        f"""SELECT
                u.id, u.name, u.username, dp.preferred_agent, dp.streak_days,
                COALESCE(scores.avg_score, 0) as total_score,
                COALESCE(scores.challenge_count, 0) as challenges_completed
            FROM developer_profiles dp
            JOIN users u ON dp.user_id = u.id
            JOIN (
                SELECT best.user_id,
                       SUM(best.best_score * best.weight) / SUM(best.weight) as avg_score,
                       COUNT(*) as challenge_count
                FROM (
                    SELECT sub.user_id, sub.challenge_id, MAX(sub.score) as best_score,
                           CASE c.difficulty WHEN 'easy' THEN 1.0 WHEN 'medium' THEN 1.5 WHEN 'hard' THEN 2.0 ELSE 1.0 END as weight
                    FROM submissions sub
                    JOIN challenges c ON sub.challenge_id = c.id
                    WHERE {sub_where}
                    GROUP BY sub.user_id, sub.challenge_id
                ) best
                GROUP BY best.user_id
            ) scores ON scores.user_id = u.id
            ORDER BY scores.avg_score DESC
            LIMIT ? OFFSET ?""",
        tuple(sub_params + [limit, offset]),
    )

    for i, row in enumerate(rows):
        row["rank"] = offset + i + 1
        if agent:
            row["preferred_agent"] = agent

    # Count total
    count_where = sub_where.replace("sub.", "s.")
    total = fetch_one(
        f"""SELECT COUNT(DISTINCT s.user_id) as count
            FROM submissions s
            JOIN challenges c ON s.challenge_id = c.id
            WHERE {count_where}""",
        tuple(sub_params),
    )

    return {
        "entries": rows,
        "total": total["count"] if total else 0,
        "page": page,
        "limit": limit,
    }


@router.get("/categories")
def leaderboard_categories() -> list[dict]:
    """List categories that have scored submissions."""
    rows = fetch_all(
        """SELECT c.category, COUNT(DISTINCT s.user_id) as developer_count, COUNT(DISTINCT s.challenge_id) as challenge_count
           FROM submissions s
           JOIN challenges c ON s.challenge_id = c.id
           WHERE s.status = 'scored'
           GROUP BY c.category
           ORDER BY developer_count DESC""",
    )
    return rows


@router.get("/challenges/{challenge_id}")
def challenge_leaderboard(
    challenge_id: str,
    agent: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    """Per-challenge leaderboard — best scores for a specific challenge."""
    conditions = ["le.challenge_id = ?"]
    params: list = [challenge_id]

    if agent:
        conditions.append("le.agent_used = ?")
        params.append(agent)

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT le.*, u.name, u.username
            FROM leaderboard_entries le
            JOIN users u ON le.user_id = u.id
            WHERE {where}
            ORDER BY le.score DESC
            LIMIT ? OFFSET ?""",
        tuple(params),
    )

    for i, row in enumerate(rows):
        row["rank"] = offset + i + 1

    total = fetch_one(
        f"SELECT COUNT(*) as count FROM leaderboard_entries le WHERE {where}",
        tuple(params[:-2]),
    )

    return {
        "entries": rows,
        "total": total["count"] if total else 0,
        "page": page,
        "limit": limit,
    }


@router.get("/me")
def my_rankings(current_user: CurrentUser) -> list[dict]:
    """Current developer's rankings across all challenges."""
    rows = fetch_all(
        """SELECT le.*, c.title as challenge_title, c.slug as challenge_slug, c.difficulty
           FROM leaderboard_entries le
           JOIN challenges c ON le.challenge_id = c.id
           WHERE le.user_id = ?
           ORDER BY le.score DESC""",
        (current_user["id"],),
    )
    return rows
