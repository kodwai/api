from __future__ import annotations

import json
import secrets
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one

router = APIRouter(tags=["admin-submissions"])


@router.get("/submissions")
def list_submissions(
    current_admin: AdminUser,
    challenge_id: Optional[str] = None,
    agent_used: Optional[str] = None,
    sub_status: Optional[str] = Query(None, alias="status"),
    user_id: Optional[str] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if challenge_id:
        conditions.append("s.challenge_id = ?")
        params.append(challenge_id)
    if agent_used:
        conditions.append("s.agent_used = ?")
        params.append(agent_used)
    if sub_status:
        conditions.append("s.status = ?")
        params.append(sub_status)
    if user_id:
        conditions.append("s.user_id = ?")
        params.append(user_id)
    if search:
        conditions.append("(u.name LIKE ? OR u.email LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT s.id, s.status, s.agent_used, s.score, s.time_taken_ms, s.started_at, s.submitted_at, s.scored_at,
                   u.name as user_name, u.email as user_email, u.username,
                   c.title as challenge_title, c.slug as challenge_slug, c.difficulty
            FROM submissions s
            JOIN users u ON s.user_id = u.id
            JOIN challenges c ON s.challenge_id = c.id
            WHERE {where}
            ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    total = fetch_one(
        f"SELECT COUNT(*) as count FROM submissions s JOIN users u ON s.user_id = u.id JOIN challenges c ON s.challenge_id = c.id WHERE {where}",
        tuple(count_params),
    )
    return {"submissions": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.get("/submissions/{submission_id}")
def get_submission(submission_id: str, current_admin: AdminUser) -> dict:
    sub = fetch_one(
        """SELECT s.*, u.name as user_name, u.email as user_email, u.username,
                  c.title as challenge_title, c.slug as challenge_slug, c.difficulty, c.time_limit_minutes
           FROM submissions s
           JOIN users u ON s.user_id = u.id
           JOIN challenges c ON s.challenge_id = c.id
           WHERE s.id = ?""",
        (submission_id,),
    )
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    sub["score_breakdown"] = json.loads(sub["score_breakdown"]) if sub.get("score_breakdown") else None
    sub["test_results"] = json.loads(sub["test_results"]) if sub.get("test_results") else None
    # Don't send full code_snapshot/agent_trace to keep response small — just counts
    code = json.loads(sub["code_snapshot"]) if sub.get("code_snapshot") else []
    sub["file_count"] = len(code) if isinstance(code, list) else 0
    sub["has_agent_trace"] = bool(sub.get("agent_trace"))
    del sub["code_snapshot"]
    del sub["agent_trace"]
    del sub["git_diff"]
    del sub["git_log"]

    return sub


@router.post("/submissions/{submission_id}/rescore")
def rescore_submission(submission_id: str, current_admin: AdminUser) -> dict:
    sub = fetch_one("SELECT id, status FROM submissions WHERE id = ?", (submission_id,))
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    execute("UPDATE submissions SET status = 'scoring', updated_at = datetime('now') WHERE id = ?", (submission_id,))

    from app.services.challenge_scoring import score_submission
    threading.Thread(target=score_submission, args=(submission_id,), daemon=True).start()

    audit_id = secrets.token_hex(16)
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, 'rescore_submission', 'submission', ?, '{}')",
        (audit_id, current_admin["id"], submission_id),
    )

    return {"status": "scoring", "message": "Re-scoring triggered"}
