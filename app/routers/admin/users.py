from __future__ import annotations

import json
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one

router = APIRouter(tags=["admin-users"])


@router.get("/users")
def list_users(
    current_admin: AdminUser,
    user_type: Optional[str] = None,
    verified: Optional[bool] = None,
    banned: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    """List all users with filters."""
    conditions = ["1=1"]
    params: list = []

    if user_type:
        conditions.append("user_type = ?")
        params.append(user_type)
    if verified is not None:
        conditions.append("email_verified = ?")
        params.append(1 if verified else 0)
    if banned is not None:
        conditions.append("is_banned = ?")
        params.append(1 if banned else 0)
    if search:
        conditions.append("(name LIKE ? OR email LIKE ? OR username LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * limit

    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT id, name, email, username, user_type, role, email_verified,
                   is_banned, is_superadmin, created_at
            FROM users WHERE {where}
            ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )

    total = fetch_one(f"SELECT COUNT(*) as count FROM users WHERE {where}", tuple(count_params))

    return {"users": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.get("/users/{user_id}")
def get_user(user_id: str, current_admin: AdminUser) -> dict:
    """Get full user details."""
    user = fetch_one(
        """SELECT id, name, email, username, user_type, role, organization_id,
                  email_verified, is_banned, banned_reason, banned_at, is_superadmin, created_at
           FROM users WHERE id = ?""",
        (user_id,),
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result = dict(user)

    # Add org info for company users
    if user["organization_id"]:
        org = fetch_one("SELECT id, name FROM organizations WHERE id = ?", (user["organization_id"],))
        result["organization"] = org

    # Add profile info for developers
    if user["user_type"] == "developer":
        profile = fetch_one(
            "SELECT total_score, challenges_completed, rank, preferred_agent, streak_days FROM developer_profiles WHERE user_id = ?",
            (user_id,),
        )
        result["developer_profile"] = profile

    # Add submissions for developers
    sub_count = fetch_one("SELECT COUNT(*) as count FROM submissions WHERE user_id = ?", (user_id,))
    result["submission_count"] = sub_count["count"] if sub_count else 0

    if user["user_type"] == "developer":
        result["recent_submissions"] = fetch_all(
            """SELECT s.id, s.status, s.agent_used, s.score, s.time_taken_ms, s.started_at,
                      c.title as challenge_title, c.slug as challenge_slug, c.difficulty
               FROM submissions s JOIN challenges c ON s.challenge_id = c.id
               WHERE s.user_id = ? ORDER BY s.created_at DESC LIMIT 20""",
            (user_id,),
        )

    if user["organization_id"]:
        sess_count = fetch_one("SELECT COUNT(*) as count FROM sessions WHERE organization_id = ?", (user["organization_id"],))
        result["session_count"] = sess_count["count"] if sess_count else 0

    return result


class UserPatchRequest(BaseModel):
    email_verified: Optional[bool] = None
    is_banned: Optional[bool] = None
    banned_reason: Optional[str] = None
    role: Optional[str] = None
    is_superadmin: Optional[bool] = None


@router.patch("/users/{user_id}")
def patch_user(user_id: str, body: UserPatchRequest, current_admin: AdminUser) -> dict:
    """Update user fields (verify, ban, role, superadmin). Logs to audit."""
    user = fetch_one("SELECT id, name, email, is_banned, is_superadmin, role, email_verified FROM users WHERE id = ?", (user_id,))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Cannot modify yourself
    if user_id == current_admin["id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot modify your own account from admin panel")

    updates: list[str] = []
    params: list = []
    actions: list[str] = []
    details: dict = {}

    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "email_verified":
            updates.append("email_verified = ?")
            params.append(1 if value else 0)
            actions.append("verify_email" if value else "unverify_email")
            details["email_verified"] = value

        elif field == "is_banned":
            updates.append("is_banned = ?")
            params.append(1 if value else 0)
            if value:
                updates.append("banned_at = datetime('now')")
                if body.banned_reason:
                    updates.append("banned_reason = ?")
                    params.append(body.banned_reason)
                actions.append("ban_user")
                details["banned_reason"] = body.banned_reason
            else:
                updates.append("banned_reason = NULL")
                updates.append("banned_at = NULL")
                actions.append("unban_user")

        elif field == "banned_reason":
            pass  # Handled with is_banned

        elif field == "role":
            if value not in ("admin", "interviewer", "viewer"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")
            updates.append("role = ?")
            params.append(value)
            actions.append("change_role")
            details["old_role"] = user["role"]
            details["new_role"] = value

        elif field == "is_superadmin":
            updates.append("is_superadmin = ?")
            params.append(1 if value else 0)
            actions.append("toggle_superadmin")
            details["is_superadmin"] = value

    if updates:
        params.append(user_id)
        execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(params))

        # Audit log
        for action in actions:
            audit_id = secrets.token_hex(16)
            execute(
                "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, ?, 'user', ?, ?)",
                (audit_id, current_admin["id"], action, user_id, json.dumps(details)),
            )

    return get_user(user_id, current_admin)
