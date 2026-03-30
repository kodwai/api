from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import CurrentUser
from app.schemas.session import (
    SessionConfigResponse,
    SessionCreate,
    SessionEndRequest,
    SessionEventCreate,
    SessionFileChange,
    SessionResponse,
)
from app.services.email_service import send_session_invitation_email
from app.services.encryption_service import decrypt_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION_COLUMNS = """
    s.id, s.project_id, s.api_key_id, s.organization_id,
    s.candidate_name, s.candidate_email, s.status, s.session_token,
    s.started_at, s.ended_at, s.end_reason, s.total_cost_usd,
    s.total_tokens, s.max_budget_usd, s.created_at, s.updated_at,
    p.title AS project_title
"""


def _row_to_response(row: dict) -> SessionResponse:
    return SessionResponse(**row)


def verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify the HMAC-SHA256 signature sent by the CLI."""
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


async def _get_session_and_verify_hmac(session_id: str, request: Request) -> tuple[dict, bytes]:
    """Look up session, read raw body, and verify HMAC. Returns (session, body)."""
    session = fetch_one(
        "SELECT * FROM sessions WHERE id = ?",
        (session_id,),
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    signature = request.headers.get("X-Kodwai-Signature", "")
    if not signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing signature")

    body = await request.body()
    if not verify_webhook_signature(body, signature, session["webhook_secret"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    return session, body


# ---------------------------------------------------------------------------
# Org-scoped endpoints (require JWT auth)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[SessionResponse])
def list_sessions(
    current_user: CurrentUser,
    project_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[SessionResponse]:
    """List sessions for the current user's organization."""
    org_id = current_user["organization_id"]

    query = f"""
        SELECT {_SESSION_COLUMNS}
        FROM sessions s
        JOIN projects p ON s.project_id = p.id
        WHERE s.organization_id = ?
    """
    params: list = [org_id]

    if project_id is not None:
        query += " AND s.project_id = ?"
        params.append(project_id)
    if status_filter is not None:
        query += " AND s.status = ?"
        params.append(status_filter)

    query += " ORDER BY s.created_at DESC"

    rows = fetch_all(query, tuple(params))
    return [_row_to_response(row) for row in rows]


@router.post("", response_model=SessionResponse, status_code=201)
def create_session(body: SessionCreate, current_user: CurrentUser) -> SessionResponse:
    """Create a new interview session and send invitation email."""
    org_id = current_user["organization_id"]

    # Validate project belongs to org
    project = fetch_one(
        "SELECT id, title, time_limit_minutes FROM projects WHERE id = ? AND organization_id = ? AND is_archived = 0",
        (body.project_id, org_id),
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Validate API key belongs to org
    api_key = fetch_one(
        "SELECT id FROM api_keys WHERE id = ? AND organization_id = ? AND is_active = 1",
        (body.api_key_id, org_id),
    )
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    session_id = secrets.token_hex(16)
    session_token = secrets.token_hex(32)
    webhook_secret = secrets.token_hex(16)

    execute(
        """INSERT INTO sessions
           (id, project_id, api_key_id, organization_id, candidate_name,
            candidate_email, status, session_token, webhook_secret, max_budget_usd)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
        (
            session_id,
            body.project_id,
            body.api_key_id,
            org_id,
            body.candidate_name,
            body.candidate_email,
            session_token,
            webhook_secret,
            body.max_budget_usd,
        ),
    )

    # Send invitation email
    send_session_invitation_email(
        to=body.candidate_email,
        candidate_name=body.candidate_name,
        project_title=project["title"],
        session_id=session_id,
        session_token=session_token,
        time_limit=project["time_limit_minutes"],
        base_url=settings.APP_URL,
    )

    row = fetch_one(
        f"""SELECT {_SESSION_COLUMNS}
            FROM sessions s
            JOIN projects p ON s.project_id = p.id
            WHERE s.id = ?""",
        (session_id,),
    )
    return _row_to_response(row)  # type: ignore[arg-type]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: str, current_user: CurrentUser) -> SessionResponse:
    """Get a single session (must belong to user's org)."""
    org_id = current_user["organization_id"]

    row = fetch_one(
        f"""SELECT {_SESSION_COLUMNS}
            FROM sessions s
            JOIN projects p ON s.project_id = p.id
            WHERE s.id = ? AND s.organization_id = ?""",
        (session_id, org_id),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return _row_to_response(row)


@router.get("/{session_id}/events")
def list_session_events(session_id: str, current_user: CurrentUser) -> dict:
    """List all events for a session (must belong to user's org)."""
    org_id = current_user["organization_id"]

    session = fetch_one(
        "SELECT id FROM sessions WHERE id = ? AND organization_id = ?",
        (session_id, org_id),
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    events = fetch_all(
        """SELECT id, event_type as type, data, timestamp
           FROM session_events
           WHERE session_id = ?
           ORDER BY timestamp ASC""",
        (session_id,),
    )

    # Parse JSON data field
    import json as _json
    for e in events:
        if isinstance(e.get("data"), str):
            try:
                e["data"] = _json.loads(e["data"])
            except (ValueError, TypeError):
                pass

    # Also fetch file changes and merge them in
    file_changes = fetch_all(
        """SELECT file_path, content, change_type, timestamp
           FROM file_changes
           WHERE session_id = ?
           ORDER BY timestamp ASC""",
        (session_id,),
    )
    for fc in file_changes:
        events.append({
            "type": "file.change",
            "data": {
                "file_path": fc["file_path"],
                "content": fc["content"],
                "change_type": fc["change_type"],
            },
            "timestamp": fc["timestamp"],
        })

    # Sort all events by timestamp
    events.sort(key=lambda e: e.get("timestamp", ""))

    return {"events": events}


# ---------------------------------------------------------------------------
# Public / CLI endpoints (no JWT — authenticated via token or HMAC)
# ---------------------------------------------------------------------------


@router.get("/{session_id}/config", response_model=SessionConfigResponse)
def get_session_config(
    session_id: str,
    session_token: str = Query(..., description="Session token for authentication"),
) -> SessionConfigResponse:
    """Public endpoint: return session config to CLI. Authenticates via session_token."""
    session = fetch_one(
        "SELECT * FROM sessions WHERE id = ? AND session_token = ?",
        (session_id, session_token),
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is already '{session['status']}' and cannot be started",
        )

    # Fetch project
    project = fetch_one(
        """SELECT title, problem_statement_md, time_limit_minutes, difficulty,
                  allowed_tools, disallowed_tools, rubric, max_budget_usd
           FROM projects WHERE id = ?""",
        (session["project_id"],),
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Fetch and decrypt API key
    api_key_row = fetch_one(
        "SELECT encrypted_key, key_iv FROM api_keys WHERE id = ?",
        (session["api_key_id"],),
    )
    if api_key_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    decrypted_key = decrypt_api_key(
        api_key_row["encrypted_key"],
        api_key_row["key_iv"],
        settings.ENCRYPTION_KEY,
    )

    # Mark session as active
    now = datetime.now(timezone.utc).isoformat()
    execute(
        "UPDATE sessions SET status = 'active', started_at = ?, updated_at = ? WHERE id = ?",
        (now, now, session_id),
    )


    # Determine budget: session override > project default
    budget = session["max_budget_usd"] or project["max_budget_usd"]

    rubric = json.loads(project["rubric"]) if project["rubric"] else []
    allowed_tools = json.loads(project["allowed_tools"]) if project["allowed_tools"] else None
    disallowed_tools = json.loads(project["disallowed_tools"]) if project["disallowed_tools"] else None

    return SessionConfigResponse(
        session_id=session_id,
        session_token=session["session_token"],
        webhook_secret=session["webhook_secret"],
        api_key=decrypted_key,
        project_title=project["title"],
        problem_statement_md=project["problem_statement_md"],
        time_limit_minutes=project["time_limit_minutes"],
        difficulty=project["difficulty"],
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
        rubric=rubric,
        max_budget_usd=budget,
        starter_files=None,  # Will be populated when starter files feature is added
    )


@router.post("/{session_id}/events", status_code=201)
async def create_session_event(session_id: str, request: Request) -> dict:
    """Receive events from CLI. Validated via HMAC signature."""
    session, body = await _get_session_and_verify_hmac(session_id, request)

    payload = json.loads(body)
    event = SessionEventCreate(**payload)

    event_id = secrets.token_hex(16)
    now = datetime.now(timezone.utc).isoformat()

    execute(
        """INSERT INTO session_events (id, session_id, event_type, data, timestamp, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            session_id,
            event.event_type,
            json.dumps(event.data) if event.data else None,
            event.timestamp or now,
            now,
        ),
    )


    return {"id": event_id, "status": "stored"}


@router.post("/{session_id}/files", status_code=201)
async def create_session_file(session_id: str, request: Request) -> dict:
    """Receive file changes from CLI. Validated via HMAC signature."""
    session, body = await _get_session_and_verify_hmac(session_id, request)

    payload = json.loads(body)
    file_change = SessionFileChange(**payload)

    change_id = secrets.token_hex(16)
    now = datetime.now(timezone.utc).isoformat()

    execute(
        """INSERT INTO file_changes (id, session_id, file_path, content, change_type, timestamp, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            change_id,
            session_id,
            file_change.file_path,
            file_change.content,
            file_change.change_type,
            file_change.timestamp or now,
            now,
        ),
    )


    return {"id": change_id, "status": "stored"}


@router.post("/{session_id}/end")
async def end_session(session_id: str, request: Request) -> dict:
    """End a session. Validated via HMAC signature."""
    session, body = await _get_session_and_verify_hmac(session_id, request)

    if session["status"] not in ("active", "pending"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is already '{session['status']}'",
        )

    payload = json.loads(body)
    end_data = SessionEndRequest(**payload)

    now = datetime.now(timezone.utc).isoformat()

    execute(
        """UPDATE sessions
           SET status = 'completed', ended_at = ?, end_reason = ?,
               total_cost_usd = ?, total_tokens = ?, updated_at = ?
           WHERE id = ?""",
        (
            now,
            end_data.end_reason,
            end_data.total_cost_usd,
            end_data.total_tokens,
            now,
            session_id,
        ),
    )

    # Store final files if provided
    if end_data.final_files:
        for f in end_data.final_files:
            file_id = secrets.token_hex(16)
            execute(
                """INSERT INTO file_changes (id, session_id, file_path, content, change_type, timestamp, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    file_id,
                    session_id,
                    f.file_path,
                    f.content,
                    f.change_type,
                    f.timestamp or now,
                    now,
                ),
            )



    # Trigger AI scoring in background thread (non-blocking)
    import threading
    from app.services.scoring_service import trigger_ai_scoring

    def _score_in_background():
        try:
            trigger_ai_scoring(session_id)
        except Exception:
            logger.exception("AI scoring failed for session %s", session_id)

    threading.Thread(target=_score_in_background, daemon=True).start()

    return {"status": "completed", "ended_at": now}
