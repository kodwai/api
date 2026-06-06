from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Query

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one

router = APIRouter(tags=["admin-leaderboard"])


@router.get("/leaderboard")
def admin_leaderboard(
    current_admin: AdminUser,
    agent: Optional[str] = None,
    model: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    offset = (page - 1) * limit

    if agent or category or model:
        # Filtered: compute scores from matching submissions only.
        # leaderboard_eligible = 1 excludes submissions rated without the AI phase.
        sub_conditions = ["sub.status = 'scored'", "sub.score IS NOT NULL", "sub.leaderboard_eligible = 1"]
        sub_params: list = []
        if agent:
            sub_conditions.append("sub.agent_used = ?")
            sub_params.append(agent)
        if model:
            sub_conditions.append("sub.model = ?")
            sub_params.append(model)
        if category:
            sub_conditions.append("c.category = ?")
            sub_params.append(category)
        sub_where = " AND ".join(sub_conditions)

        rows = fetch_all(
            f"""SELECT u.id, u.name, u.username, u.email, dp.preferred_agent, dp.streak_days,
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
        count_where = sub_where.replace("sub.", "s.")
        total = fetch_one(
            f"SELECT COUNT(DISTINCT s.user_id) as count FROM submissions s JOIN challenges c ON s.challenge_id = c.id WHERE {count_where}",
            tuple(sub_params),
        )
    else:
        # Default: use profile scores
        conditions = ["dp.challenges_completed > 0"]
        params: list = []
        if search:
            conditions.append("(u.name LIKE ? OR u.email LIKE ? OR u.username LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
        where = " AND ".join(conditions)
        count_params = list(params)
        params.extend([limit, offset])

        rows = fetch_all(
            f"""SELECT u.id, u.name, u.username, u.email, dp.total_score, dp.challenges_completed,
                       dp.preferred_agent, dp.rank, dp.streak_days
                FROM developer_profiles dp
                JOIN users u ON dp.user_id = u.id
                WHERE {where}
                ORDER BY dp.total_score DESC
                LIMIT ? OFFSET ?""",
            tuple(params),
        )
        total = fetch_one(f"SELECT COUNT(*) as count FROM developer_profiles dp JOIN users u ON dp.user_id = u.id WHERE {where}", tuple(count_params))

    for i, row in enumerate(rows):
        row["rank"] = offset + i + 1
        if agent:
            row["preferred_agent"] = agent

    return {"entries": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.post("/leaderboard/recalculate")
def recalculate_ranks(current_admin: AdminUser) -> dict:
    # Reuse the scoring engine's ranking rule: only developers with a leaderboard-
    # eligible (AI-scored) submission are ranked; everyone else has rank cleared.
    from app.services.challenge_scoring import _recompute_ranks

    _recompute_ranks()
    profiles = fetch_all(
        "SELECT user_id FROM developer_profiles WHERE rank IS NOT NULL",
    )

    audit_id = secrets.token_hex(16)
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, 'recalculate_ranks', 'leaderboard', 'global', ?)",
        (audit_id, current_admin["id"], f'{{"updated_count": {len(profiles)}}}'),
    )
    return {"recalculated": len(profiles)}
