from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.admin_deps import AdminUser
from app.core.database import fetch_all, fetch_one

router = APIRouter(tags=["admin-organizations"])


@router.get("/organizations")
def list_organizations(
    current_admin: AdminUser,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if search:
        conditions.append("o.name LIKE ?")
        params.append(f"%{search}%")

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT o.id, o.name, o.created_at,
                   (SELECT COUNT(*) FROM users WHERE organization_id = o.id) as member_count,
                   (SELECT COUNT(*) FROM projects WHERE organization_id = o.id) as project_count,
                   (SELECT COUNT(*) FROM sessions WHERE organization_id = o.id) as session_count
            FROM organizations o WHERE {where}
            ORDER BY o.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    total = fetch_one(f"SELECT COUNT(*) as count FROM organizations o WHERE {where}", tuple(count_params))
    return {"organizations": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.get("/organizations/{org_id}")
def get_organization(org_id: str, current_admin: AdminUser) -> dict:
    org = fetch_one("SELECT * FROM organizations WHERE id = ?", (org_id,))
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    members = fetch_all(
        "SELECT id, name, email, role, email_verified, created_at FROM users WHERE organization_id = ?",
        (org_id,),
    )
    projects = fetch_all(
        "SELECT id, title, difficulty, is_archived, created_at FROM projects WHERE organization_id = ? ORDER BY created_at DESC LIMIT 20",
        (org_id,),
    )
    sessions = fetch_all(
        """SELECT s.id, s.candidate_name, s.candidate_email, s.status, s.created_at, p.title as project_title
           FROM sessions s JOIN projects p ON s.project_id = p.id
           WHERE s.organization_id = ? ORDER BY s.created_at DESC LIMIT 20""",
        (org_id,),
    )

    return {**org, "members": members, "projects": projects, "recent_sessions": sessions}
