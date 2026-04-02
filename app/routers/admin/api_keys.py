from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, HTTPException, Query, status

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one

router = APIRouter(tags=["admin-api-keys"])


@router.get("/api-keys")
def list_all_keys(
    current_admin: AdminUser,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    """List all API keys across all orgs and users (masked)."""
    offset = (page - 1) * limit
    rows = fetch_all(
        """SELECT k.id, k.key_last4, k.label, k.is_active, k.created_at,
                  k.organization_id, k.user_id,
                  COALESCE(o.name, '') as org_name,
                  COALESCE(u.name, '') as user_name,
                  COALESCE(u.email, '') as user_email,
                  u.user_type
           FROM api_keys k
           LEFT JOIN organizations o ON k.organization_id = o.id
           LEFT JOIN users u ON k.user_id = u.id OR (k.organization_id IS NOT NULL AND u.organization_id = k.organization_id AND u.role = 'admin')
           GROUP BY k.id
           ORDER BY k.created_at DESC LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    for r in rows:
        r["is_active"] = bool(r.get("is_active", 1))

    total = fetch_one("SELECT COUNT(*) as count FROM api_keys")
    return {"keys": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.patch("/api-keys/{key_id}/deactivate")
def deactivate_key(key_id: str, current_admin: AdminUser) -> dict:
    k = fetch_one("SELECT id, is_active, label FROM api_keys WHERE id = ?", (key_id,))
    if k is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
    execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
    audit_id = secrets.token_hex(16)
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, 'deactivate_key', 'api_key', ?, ?)",
        (audit_id, current_admin["id"], key_id, json.dumps({"label": k["label"]})),
    )
    return {"is_active": False}


@router.patch("/api-keys/{key_id}/activate")
def activate_key(key_id: str, current_admin: AdminUser) -> dict:
    k = fetch_one("SELECT id FROM api_keys WHERE id = ?", (key_id,))
    if k is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
    execute("UPDATE api_keys SET is_active = 1 WHERE id = ?", (key_id,))
    return {"is_active": True}
