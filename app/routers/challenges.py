from __future__ import annotations

import json
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import AdminUser, CurrentUser
from app.schemas.challenge import (
    CategoryCount,
    ChallengeCreate,
    ChallengeListResponse,
    ChallengeResponse,
    ChallengeUpdate,
)

router = APIRouter(tags=["challenges"])


def _row_to_response(row: dict, hide_problem: bool = False) -> ChallengeResponse:
    data = dict(row)
    data["tags"] = json.loads(data["tags"]) if data.get("tags") else []
    data["test_suite"] = json.loads(data["test_suite"]) if data.get("test_suite") else None
    data["scoring_config"] = json.loads(data["scoring_config"]) if data.get("scoring_config") else {}
    data["starter_files"] = json.loads(data["starter_files"]) if data.get("starter_files") else None
    data["allowed_tools"] = json.loads(data["allowed_tools"]) if data.get("allowed_tools") else None
    data["disallowed_tools"] = json.loads(data["disallowed_tools"]) if data.get("disallowed_tools") else None
    data["is_public"] = bool(data.get("is_public", 1))
    data["is_featured"] = bool(data.get("is_featured", 0))
    if hide_problem:
        data["problem_statement_md"] = None
        data["starter_files"] = None
        data["test_suite"] = None
    return ChallengeResponse(**data)


def _row_to_list_response(row: dict) -> ChallengeListResponse:
    data = dict(row)
    data["tags"] = json.loads(data["tags"]) if data.get("tags") else []
    data["is_featured"] = bool(data.get("is_featured", 0))
    return ChallengeListResponse(**data)


def _get_challenge_or_404(id_or_slug: str) -> dict:
    challenge = fetch_one(
        """SELECT * FROM challenges WHERE id = ? OR slug = ?""",
        (id_or_slug, id_or_slug),
    )
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")
    return challenge


# ── Public endpoints ──


@router.get("/challenges", response_model=list[ChallengeListResponse])
def list_challenges(
    difficulty: Optional[str] = Query(None, pattern=r"^(easy|medium|hard)$"),
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = Query("newest", pattern=r"^(newest|popular|difficulty)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> list[ChallengeListResponse]:
    """Browse published challenges."""
    conditions = ["is_public = 1"]
    params: list = []

    if difficulty:
        conditions.append("difficulty = ?")
        params.append(difficulty)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if search:
        conditions.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)

    order = {
        "newest": "created_at DESC",
        "popular": "submission_count DESC",
        "difficulty": "CASE difficulty WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 WHEN 'hard' THEN 3 END",
    }.get(sort, "created_at DESC")

    offset = (page - 1) * limit
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT id, title, slug, description, difficulty, category, tags,
                   time_limit_minutes, is_featured, submission_count, avg_score
            FROM challenges WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?""",
        tuple(params),
    )
    return [_row_to_list_response(row) for row in rows]


@router.get("/challenges/categories", response_model=list[CategoryCount])
def list_categories() -> list[CategoryCount]:
    """List challenge categories with counts."""
    rows = fetch_all(
        "SELECT category, COUNT(*) as count FROM challenges WHERE is_public = 1 GROUP BY category ORDER BY count DESC",
    )
    return [CategoryCount(**row) for row in rows]


@router.get("/challenges/featured", response_model=list[ChallengeListResponse])
def list_featured() -> list[ChallengeListResponse]:
    """List featured challenges."""
    rows = fetch_all(
        """SELECT id, title, slug, description, difficulty, category, tags,
                  time_limit_minutes, is_featured, submission_count, avg_score
           FROM challenges WHERE is_public = 1 AND is_featured = 1
           ORDER BY created_at DESC LIMIT 10""",
    )
    return [_row_to_list_response(row) for row in rows]


@router.get("/challenges/{id_or_slug}", response_model=ChallengeResponse)
def get_challenge(id_or_slug: str) -> ChallengeResponse:
    """Get challenge detail. Problem statement is hidden (revealed on start)."""
    challenge = _get_challenge_or_404(id_or_slug)
    return _row_to_response(challenge, hide_problem=True)


# ── Admin endpoints ──


@router.post("/admin/challenges", response_model=ChallengeResponse, status_code=201)
def create_challenge(body: ChallengeCreate, current_user: AdminUser) -> ChallengeResponse:
    """Admin: create a new challenge."""
    # Check slug uniqueness
    existing = fetch_one("SELECT id FROM challenges WHERE slug = ?", (body.slug,))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")

    challenge_id = secrets.token_hex(16)
    execute(
        """INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md,
                  difficulty, category, tags, time_limit_minutes, test_suite, scoring_config,
                  starter_files, allowed_tools, disallowed_tools, max_budget_usd, is_public, is_featured)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            challenge_id, current_user["id"], body.title, body.slug, body.description,
            body.problem_statement_md, body.difficulty, body.category,
            json.dumps(body.tags), body.time_limit_minutes,
            json.dumps(body.test_suite) if body.test_suite else None,
            json.dumps(body.scoring_config),
            json.dumps(body.starter_files) if body.starter_files else None,
            json.dumps(body.allowed_tools) if body.allowed_tools else None,
            json.dumps(body.disallowed_tools) if body.disallowed_tools else None,
            body.max_budget_usd, int(body.is_public), int(body.is_featured),
        ),
    )

    row = fetch_one("SELECT * FROM challenges WHERE id = ?", (challenge_id,))
    return _row_to_response(row)  # type: ignore[arg-type]


@router.put("/admin/challenges/{challenge_id}", response_model=ChallengeResponse)
def update_challenge(challenge_id: str, body: ChallengeUpdate, current_user: AdminUser) -> ChallengeResponse:
    """Admin: update a challenge."""
    existing = fetch_one("SELECT id FROM challenges WHERE id = ?", (challenge_id,))
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    updates: list[str] = []
    params: list = []
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in ("tags", "test_suite", "scoring_config", "starter_files", "allowed_tools", "disallowed_tools"):
            value = json.dumps(value) if value is not None else None
        if field in ("is_public", "is_featured"):
            value = int(value) if value is not None else None
        updates.append(f"{field} = ?")
        params.append(value)

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(challenge_id)
        execute(f"UPDATE challenges SET {', '.join(updates)} WHERE id = ?", tuple(params))

    row = fetch_one("SELECT * FROM challenges WHERE id = ?", (challenge_id,))
    return _row_to_response(row)  # type: ignore[arg-type]


@router.delete("/admin/challenges/{challenge_id}", status_code=204)
def delete_challenge(challenge_id: str, current_user: AdminUser):
    """Admin: delete a challenge."""
    existing = fetch_one("SELECT id FROM challenges WHERE id = ?", (challenge_id,))
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")
    execute("DELETE FROM challenges WHERE id = ?", (challenge_id,))
    return None


@router.get("/admin/challenges", response_model=list[ChallengeResponse])
def list_all_challenges(current_user: AdminUser) -> list[ChallengeResponse]:
    """Admin: list all challenges including drafts."""
    rows = fetch_all("SELECT * FROM challenges ORDER BY created_at DESC")
    return [_row_to_response(row) for row in rows]
