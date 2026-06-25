from __future__ import annotations

import json
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one

router = APIRouter(tags=["admin-challenges"])


@router.get("/challenges")
def list_challenges(
    current_admin: AdminUser,
    difficulty: Optional[str] = None,
    category: Optional[str] = None,
    published: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    """List all challenges including unpublished."""
    conditions = ["1=1"]
    params: list = []

    if difficulty:
        conditions.append("difficulty = ?")
        params.append(difficulty)
    if category:
        conditions.append("category = ?")
        params.append(category)
    if published is not None:
        conditions.append("is_public = ?")
        params.append(1 if published else 0)
    if search:
        conditions.append("(title LIKE ? OR slug LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT id, title, slug, difficulty, category, is_public, is_featured,
                   submission_count, avg_score, created_at
            FROM challenges WHERE {where}
            ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    for r in rows:
        r["is_public"] = bool(r["is_public"])
        r["is_featured"] = bool(r["is_featured"])

    total = fetch_one(f"SELECT COUNT(*) as count FROM challenges WHERE {where}", tuple(count_params))

    return {"challenges": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.patch("/challenges/{challenge_id}/publish")
def toggle_publish(challenge_id: str, current_admin: AdminUser) -> dict:
    """Toggle is_public."""
    ch = fetch_one("SELECT id, is_public FROM challenges WHERE id = ?", (challenge_id,))
    if ch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")
    new_val = 0 if ch["is_public"] else 1
    execute("UPDATE challenges SET is_public = ?, updated_at = datetime('now') WHERE id = ?", (new_val, challenge_id))
    _audit(current_admin["id"], "toggle_publish", "challenge", challenge_id, {"is_public": bool(new_val)})
    return {"is_public": bool(new_val)}


@router.patch("/challenges/{challenge_id}/feature")
def toggle_feature(challenge_id: str, current_admin: AdminUser) -> dict:
    """Toggle is_featured."""
    ch = fetch_one("SELECT id, is_featured FROM challenges WHERE id = ?", (challenge_id,))
    if ch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")
    new_val = 0 if ch["is_featured"] else 1
    execute("UPDATE challenges SET is_featured = ?, updated_at = datetime('now') WHERE id = ?", (new_val, challenge_id))
    _audit(current_admin["id"], "toggle_feature", "challenge", challenge_id, {"is_featured": bool(new_val)})
    return {"is_featured": bool(new_val)}


class ChallengeCreateUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    problem_statement_md: Optional[str] = None
    difficulty: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    time_limit_minutes: Optional[int] = None
    test_suite: Optional[list[dict]] = None
    starter_files: Optional[list[dict]] = None
    scoring_config: Optional[dict] = None
    is_public: Optional[bool] = None
    is_featured: Optional[bool] = None


@router.post("/challenges")
def create_challenge(body: ChallengeCreateUpdate, current_admin: AdminUser) -> dict:
    """Create a new challenge."""
    if not body.title or not body.slug or not body.description or not body.problem_statement_md or not body.difficulty or not body.category:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title, slug, description, problem_statement_md, difficulty, category are required")

    existing = fetch_one("SELECT id FROM challenges WHERE slug = ?", (body.slug,))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")

    cid = secrets.token_hex(16)
    execute(
        """INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category, tags, time_limit_minutes, test_suite, scoring_config, starter_files, is_public, is_featured)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cid, current_admin["id"], body.title, body.slug, body.description, body.problem_statement_md,
         body.difficulty, body.category, json.dumps(body.tags or []), body.time_limit_minutes or 60,
         json.dumps(body.test_suite) if body.test_suite else None,
         json.dumps(body.scoring_config or {}),
         json.dumps(body.starter_files) if body.starter_files else None,
         1 if body.is_public is None or body.is_public else 0,
         1 if body.is_featured else 0),
    )
    _audit(current_admin["id"], "create_challenge", "challenge", cid, {"title": body.title, "slug": body.slug})
    return fetch_one("SELECT * FROM challenges WHERE id = ?", (cid,))


@router.get("/challenges/{challenge_id}")
def get_challenge_detail(challenge_id: str, current_admin: AdminUser) -> dict:
    """Get full challenge detail for editing."""
    ch = fetch_one("SELECT * FROM challenges WHERE id = ?", (challenge_id,))
    if ch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")
    ch["tags"] = json.loads(ch["tags"]) if ch.get("tags") else []
    ch["test_suite"] = json.loads(ch["test_suite"]) if ch.get("test_suite") else None
    ch["scoring_config"] = json.loads(ch["scoring_config"]) if ch.get("scoring_config") else {}
    ch["starter_files"] = json.loads(ch["starter_files"]) if ch.get("starter_files") else None
    ch["is_public"] = bool(ch.get("is_public", 1))
    ch["is_featured"] = bool(ch.get("is_featured", 0))
    return ch


@router.put("/challenges/{challenge_id}")
def update_challenge(challenge_id: str, body: ChallengeCreateUpdate, current_admin: AdminUser) -> dict:
    """Update a challenge."""
    ch = fetch_one("SELECT id FROM challenges WHERE id = ?", (challenge_id,))
    if ch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    updates: list[str] = []
    params: list = []
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in ("tags", "test_suite", "scoring_config", "starter_files"):
            value = json.dumps(value) if value is not None else None
        if field in ("is_public", "is_featured"):
            value = 1 if value else 0
        updates.append(f"{field} = ?")
        params.append(value)

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(challenge_id)
        execute(f"UPDATE challenges SET {', '.join(updates)} WHERE id = ?", tuple(params))
        _audit(current_admin["id"], "update_challenge", "challenge", challenge_id, {"fields": list(body.model_dump(exclude_unset=True).keys())})

    return get_challenge_detail(challenge_id, current_admin)


@router.delete("/challenges/{challenge_id}")
def delete_challenge(challenge_id: str, current_admin: AdminUser) -> dict:
    """Hard delete a challenge."""
    ch = fetch_one("SELECT id, title FROM challenges WHERE id = ?", (challenge_id,))
    if ch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")
    execute("DELETE FROM challenges WHERE id = ?", (challenge_id,))
    _audit(current_admin["id"], "delete_challenge", "challenge", challenge_id, {"title": ch["title"]})
    return {"deleted": True}


def _audit(admin_id: str, action: str, entity_type: str, entity_id: str, details: dict) -> None:
    audit_id = secrets.token_hex(16)
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (audit_id, admin_id, action, entity_type, entity_id, json.dumps(details)),
    )
