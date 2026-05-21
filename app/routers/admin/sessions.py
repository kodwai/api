from __future__ import annotations

import json
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one

router = APIRouter(tags=["admin-sessions"])


@router.get("/sessions")
def list_sessions(
    current_admin: AdminUser,
    org_id: Optional[str] = None,
    session_status: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if org_id:
        conditions.append("s.organization_id = ?")
        params.append(org_id)
    if session_status:
        conditions.append("s.status = ?")
        params.append(session_status)
    if search:
        conditions.append("(s.candidate_name LIKE ? OR s.candidate_email LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT s.id, s.candidate_name, s.candidate_email, s.status, s.started_at, s.ended_at,
                   s.total_cost_usd, s.duration_ms, s.total_tokens, s.created_at,
                   p.title as project_title, o.name as org_name,
                   (SELECT sc.overall_score FROM scores sc WHERE sc.session_id = s.id AND sc.score_type = 'ai' LIMIT 1) as ai_score
            FROM sessions s
            JOIN projects p ON s.project_id = p.id
            JOIN organizations o ON s.organization_id = o.id
            WHERE {where}
            ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    total = fetch_one(
        f"SELECT COUNT(*) as count FROM sessions s JOIN projects p ON s.project_id = p.id WHERE {where}",
        tuple(count_params),
    )
    return {"sessions": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, current_admin: AdminUser) -> dict:
    session = fetch_one(
        """SELECT s.*, p.title as project_title, p.problem_statement_md, o.name as org_name
           FROM sessions s
           JOIN projects p ON s.project_id = p.id
           JOIN organizations o ON s.organization_id = o.id
           WHERE s.id = ?""",
        (session_id,),
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    events = fetch_all(
        "SELECT id, event_type, timestamp FROM session_events WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,),
    )
    scores = fetch_all("SELECT * FROM scores WHERE session_id = ?", (session_id,))
    for sc in scores:
        sc["dimensions"] = json.loads(sc["dimensions"]) if sc.get("dimensions") else []
        sc["strengths"] = json.loads(sc["strengths"]) if sc.get("strengths") else []
        sc["weaknesses"] = json.loads(sc["weaknesses"]) if sc.get("weaknesses") else []

    final_files = fetch_all(
        "SELECT file_path, length(content) as size FROM final_files WHERE session_id = ?",
        (session_id,),
    )
    file_change_count = fetch_one(
        "SELECT COUNT(*) as count FROM file_changes WHERE session_id = ?",
        (session_id,),
    )

    return {
        **session,
        "events": events, "event_count": len(events), "scores": scores,
        "final_files": final_files,
        "file_change_count": file_change_count["count"] if file_change_count else 0,
    }


@router.post("/sessions/{session_id}/end")
def end_session(session_id: str, current_admin: AdminUser) -> dict:
    session = fetch_one("SELECT id, status FROM sessions WHERE id = ?", (session_id,))
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session["status"] not in ("pending", "active"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session is not active")

    execute(
        "UPDATE sessions SET status = 'expired', end_reason = 'admin_terminated', ended_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (session_id,),
    )

    audit_id = secrets.token_hex(16)
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, 'end_session', 'session', ?, '{}')",
        (audit_id, current_admin["id"], session_id),
    )

    return {"status": "expired", "end_reason": "admin_terminated"}
