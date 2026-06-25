from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.admin_deps import AdminUser
from app.core.database import fetch_all, fetch_one

router = APIRouter(tags=["admin-projects"])


@router.get("/projects")
def list_projects(
    current_admin: AdminUser,
    org_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if org_id:
        conditions.append("p.organization_id = ?")
        params.append(org_id)
    if search:
        conditions.append("(p.title LIKE ? OR o.name LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT p.id, p.title, p.difficulty, p.time_limit_minutes, p.is_archived, p.created_at,
                   o.name as org_name, o.id as org_id,
                   (SELECT COUNT(*) FROM sessions WHERE project_id = p.id) as session_count,
                   (SELECT AVG(sc.overall_score) FROM scores sc JOIN sessions s ON sc.session_id = s.id WHERE s.project_id = p.id AND sc.score_type = 'ai') as avg_score
            FROM projects p
            JOIN organizations o ON p.organization_id = o.id
            WHERE {where}
            ORDER BY p.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    for r in rows:
        r["is_archived"] = bool(r.get("is_archived", 0))

    total = fetch_one(
        f"SELECT COUNT(*) as count FROM projects p JOIN organizations o ON p.organization_id = o.id WHERE {where}",
        tuple(count_params),
    )
    return {"projects": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.get("/projects/{project_id}")
def get_project(project_id: str, current_admin: AdminUser) -> dict:
    project = fetch_one(
        """SELECT p.*, o.name as org_name
           FROM projects p JOIN organizations o ON p.organization_id = o.id
           WHERE p.id = ?""",
        (project_id,),
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    project["rubric"] = json.loads(project["rubric"]) if project.get("rubric") else []
    project["allowed_tools"] = json.loads(project["allowed_tools"]) if project.get("allowed_tools") else None
    project["disallowed_tools"] = json.loads(project["disallowed_tools"]) if project.get("disallowed_tools") else None
    project["is_archived"] = bool(project.get("is_archived", 0))

    sessions = fetch_all(
        """SELECT s.id, s.candidate_name, s.candidate_email, s.status, s.started_at, s.ended_at,
                  (SELECT sc.overall_score FROM scores sc WHERE sc.session_id = s.id AND sc.score_type = 'ai' LIMIT 1) as ai_score
           FROM sessions s WHERE s.project_id = ? ORDER BY s.created_at DESC LIMIT 30""",
        (project_id,),
    )

    return {**project, "sessions": sessions, "session_count": len(sessions)}
