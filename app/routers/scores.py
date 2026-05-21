from __future__ import annotations

import json
import logging
import secrets

from fastapi import APIRouter, HTTPException, status

from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import CurrentUser
from app.schemas.score import (
    CommentCreate,
    CommentResponse,
    ScoreCreate,
    ScoreResponse,
)
from app.services.scoring_service import trigger_ai_scoring

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}", tags=["scores", "comments"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify_session_access(session_id: str, org_id: str) -> dict:
    """Verify the session exists and belongs to the user's org. Returns the session row."""
    session = fetch_one(
        "SELECT * FROM sessions WHERE id = ? AND organization_id = ?",
        (session_id, org_id),
    )
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def _parse_score_row(row: dict) -> ScoreResponse:
    """Parse JSON fields in a score row into a ScoreResponse."""
    dimensions = row.get("dimensions", "[]")
    if isinstance(dimensions, str):
        try:
            dimensions = json.loads(dimensions)
        except (ValueError, TypeError):
            dimensions = []

    strengths = row.get("strengths")
    if isinstance(strengths, str):
        try:
            strengths = json.loads(strengths)
        except (ValueError, TypeError):
            strengths = None

    weaknesses = row.get("weaknesses")
    if isinstance(weaknesses, str):
        try:
            weaknesses = json.loads(weaknesses)
        except (ValueError, TypeError):
            weaknesses = None

    return ScoreResponse(
        id=row["id"],
        session_id=row["session_id"],
        score_type=row["score_type"],
        scorer_id=row.get("scorer_id"),
        dimensions=dimensions,
        overall_score=row["overall_score"],
        summary=row.get("summary"),
        strengths=strengths,
        weaknesses=weaknesses,
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Scores endpoints
# ---------------------------------------------------------------------------


@router.get("/scores", response_model=list[ScoreResponse])
def list_scores(session_id: str, current_user: CurrentUser) -> list[ScoreResponse]:
    """List all scores (AI + manual) for a session."""
    org_id = current_user["organization_id"]
    _verify_session_access(session_id, org_id)

    rows = fetch_all(
        "SELECT * FROM scores WHERE session_id = ? ORDER BY created_at DESC",
        (session_id,),
    )
    return [_parse_score_row(row) for row in rows]


@router.post("/scores", response_model=ScoreResponse, status_code=201)
def create_manual_score(
    session_id: str,
    body: ScoreCreate,
    current_user: CurrentUser,
) -> ScoreResponse:
    """Create a manual score for a session."""
    org_id = current_user["organization_id"]
    _verify_session_access(session_id, org_id)

    score_id = secrets.token_hex(16)
    dimensions_json = json.dumps([d.model_dump() for d in body.dimensions])

    execute(
        """INSERT INTO scores (id, session_id, score_type, scorer_id, dimensions, overall_score, summary)
           VALUES (?, ?, 'manual', ?, ?, ?, ?)""",
        (
            score_id,
            session_id,
            current_user["id"],
            dimensions_json,
            body.overall_score,
            body.summary,
        ),
    )

    row = fetch_one("SELECT * FROM scores WHERE id = ?", (score_id,))
    return _parse_score_row(row)  # type: ignore[arg-type]


@router.post("/scores/trigger-ai", response_model=ScoreResponse, status_code=201)
def trigger_ai_scoring_endpoint(
    session_id: str,
    current_user: CurrentUser,
) -> ScoreResponse:
    """Manually trigger AI scoring for a completed session."""
    org_id = current_user["organization_id"]
    session = _verify_session_access(session_id, org_id)

    if session["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI scoring can only be triggered for completed sessions",
        )

    result = trigger_ai_scoring(session_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI scoring failed. Check server logs for details.",
        )

    # Fetch the newly created score
    row = fetch_one(
        "SELECT * FROM scores WHERE session_id = ? AND score_type = 'ai' ORDER BY created_at DESC LIMIT 1",
        (session_id,),
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI score was not stored",
        )
    return _parse_score_row(row)


# ---------------------------------------------------------------------------
# Comments endpoints
# ---------------------------------------------------------------------------


@router.get("/comments", response_model=list[CommentResponse])
def list_comments(session_id: str, current_user: CurrentUser) -> list[CommentResponse]:
    """List comments for a session, with user names."""
    org_id = current_user["organization_id"]
    _verify_session_access(session_id, org_id)

    rows = fetch_all(
        """SELECT c.id, c.session_id, c.user_id, u.name AS user_name,
                  c.event_id, c.content, c.created_at
           FROM comments c
           JOIN users u ON c.user_id = u.id
           WHERE c.session_id = ?
           ORDER BY c.created_at ASC""",
        (session_id,),
    )
    return [CommentResponse(**row) for row in rows]


@router.post("/comments", response_model=CommentResponse, status_code=201)
def create_comment(
    session_id: str,
    body: CommentCreate,
    current_user: CurrentUser,
) -> CommentResponse:
    """Create a comment on a session."""
    org_id = current_user["organization_id"]
    _verify_session_access(session_id, org_id)

    comment_id = secrets.token_hex(16)

    execute(
        """INSERT INTO comments (id, session_id, user_id, event_id, content)
           VALUES (?, ?, ?, ?, ?)""",
        (
            comment_id,
            session_id,
            current_user["id"],
            body.event_id,
            body.content,
        ),
    )

    row = fetch_one(
        """SELECT c.id, c.session_id, c.user_id, u.name AS user_name,
                  c.event_id, c.content, c.created_at
           FROM comments c
           JOIN users u ON c.user_id = u.id
           WHERE c.id = ?""",
        (comment_id,),
    )
    return CommentResponse(**row)  # type: ignore[arg-type]


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(
    session_id: str,
    comment_id: str,
    current_user: CurrentUser,
):
    """Delete own comment."""
    org_id = current_user["organization_id"]
    _verify_session_access(session_id, org_id)

    comment = fetch_one(
        "SELECT * FROM comments WHERE id = ? AND session_id = ?",
        (comment_id, session_id),
    )
    if comment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")

    if comment["user_id"] != current_user["id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own comments")

    execute("DELETE FROM comments WHERE id = ?", (comment_id,))
