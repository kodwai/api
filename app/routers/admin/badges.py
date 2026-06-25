from __future__ import annotations

import json
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one

router = APIRouter(tags=["admin-badges"])


@router.get("/badges")
def list_badges(current_admin: AdminUser) -> list[dict]:
    """All badges with earned counts."""
    rows = fetch_all(
        """SELECT b.*,
                  (SELECT COUNT(*) FROM developer_badges db WHERE db.badge_id = b.id) as earned_count
           FROM badges b ORDER BY b.category, b.name""",
    )
    for r in rows:
        r["criteria"] = json.loads(r["criteria"]) if r.get("criteria") else {}
        r["is_active"] = bool(r.get("is_active", 1))
    return rows


class BadgeCreateUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    category: Optional[str] = None
    criteria: Optional[dict] = None
    is_active: Optional[bool] = None


@router.post("/badges")
def create_badge(body: BadgeCreateUpdate, current_admin: AdminUser) -> dict:
    if not body.name or not body.slug or not body.description or not body.icon or not body.category:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name, slug, description, icon, category required")

    existing = fetch_one("SELECT id FROM badges WHERE slug = ?", (body.slug,))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")

    bid = secrets.token_hex(16)
    execute(
        "INSERT INTO badges (id, name, slug, description, icon, category, criteria, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (bid, body.name, body.slug, body.description, body.icon, body.category, json.dumps(body.criteria or {}), 1 if body.is_active is None or body.is_active else 0),
    )
    _audit(current_admin["id"], "create_badge", "badge", bid, {"name": body.name})
    return fetch_one("SELECT * FROM badges WHERE id = ?", (bid,))


@router.put("/badges/{badge_id}")
def update_badge(badge_id: str, body: BadgeCreateUpdate, current_admin: AdminUser) -> dict:
    b = fetch_one("SELECT id FROM badges WHERE id = ?", (badge_id,))
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found")

    updates: list[str] = []
    params: list = []
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "criteria":
            value = json.dumps(value) if value else "{}"
        if field == "is_active":
            value = 1 if value else 0
        updates.append(f"{field} = ?")
        params.append(value)

    if updates:
        params.append(badge_id)
        execute(f"UPDATE badges SET {', '.join(updates)} WHERE id = ?", tuple(params))
        _audit(current_admin["id"], "update_badge", "badge", badge_id, {"fields": list(body.model_dump(exclude_unset=True).keys())})

    row = fetch_one("SELECT * FROM badges WHERE id = ?", (badge_id,))
    row["criteria"] = json.loads(row["criteria"]) if row.get("criteria") else {}
    row["is_active"] = bool(row.get("is_active", 1))
    return row


@router.patch("/badges/{badge_id}/toggle")
def toggle_badge(badge_id: str, current_admin: AdminUser) -> dict:
    b = fetch_one("SELECT id, is_active FROM badges WHERE id = ?", (badge_id,))
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found")
    new_val = 0 if b["is_active"] else 1
    execute("UPDATE badges SET is_active = ? WHERE id = ?", (new_val, badge_id))
    _audit(current_admin["id"], "toggle_badge", "badge", badge_id, {"is_active": bool(new_val)})
    return {"is_active": bool(new_val)}


@router.delete("/badges/{badge_id}")
def delete_badge(badge_id: str, current_admin: AdminUser) -> dict:
    b = fetch_one("SELECT id, name FROM badges WHERE id = ?", (badge_id,))
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Badge not found")
    execute("DELETE FROM developer_badges WHERE badge_id = ?", (badge_id,))
    execute("DELETE FROM badges WHERE id = ?", (badge_id,))
    _audit(current_admin["id"], "delete_badge", "badge", badge_id, {"name": b["name"]})
    return {"deleted": True}


def _audit(admin_id: str, action: str, entity_type: str, entity_id: str, details: dict) -> None:
    audit_id = secrets.token_hex(16)
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (audit_id, admin_id, action, entity_type, entity_id, json.dumps(details)),
    )
