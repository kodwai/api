from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Query, status

from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import CurrentUser
from app.schemas.feedback import (
    ChallengeFeedbackCreate,
    ChallengeFeedbackResponse,
    ChallengeFeedbackSummary,
    PlatformFeedbackCreate,
    PlatformFeedbackResponse,
)

router = APIRouter(tags=["feedback"])


def _require_developer(user: dict) -> None:
    if user.get("user_type") != "developer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account required")


# ── Challenge Feedback ──────────────────────────────────────────────


@router.put("/challenges/{challenge_id}/feedback", response_model=ChallengeFeedbackResponse)
def upsert_challenge_feedback(
    challenge_id: str,
    body: ChallengeFeedbackCreate,
    current_user: CurrentUser,
) -> ChallengeFeedbackResponse:
    """Create or update feedback for a challenge (one per user per challenge)."""
    _require_developer(current_user)

    challenge = fetch_one("SELECT id FROM challenges WHERE id = ?", (challenge_id,))
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    if body.submission_id:
        sub = fetch_one(
            "SELECT id FROM submissions WHERE id = ? AND user_id = ? AND challenge_id = ?",
            (body.submission_id, current_user["id"], challenge_id),
        )
        if sub is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")

    feedback_id = secrets.token_hex(16)
    execute(
        """INSERT INTO challenge_feedback (id, challenge_id, user_id, submission_id, rating_overall, rating_difficulty, rating_clarity, comment)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, challenge_id) DO UPDATE SET
             submission_id = excluded.submission_id,
             rating_overall = excluded.rating_overall,
             rating_difficulty = excluded.rating_difficulty,
             rating_clarity = excluded.rating_clarity,
             comment = excluded.comment,
             updated_at = datetime('now')""",
        (
            feedback_id,
            challenge_id,
            current_user["id"],
            body.submission_id,
            body.rating_overall,
            body.rating_difficulty,
            body.rating_clarity,
            body.comment,
        ),
    )

    row = fetch_one(
        "SELECT * FROM challenge_feedback WHERE user_id = ? AND challenge_id = ?",
        (current_user["id"], challenge_id),
    )
    return ChallengeFeedbackResponse(**row)


@router.get("/challenges/{challenge_id}/feedback/me", response_model=ChallengeFeedbackResponse | None)
def get_my_challenge_feedback(
    challenge_id: str,
    current_user: CurrentUser,
) -> ChallengeFeedbackResponse | None:
    """Get the current user's feedback for a challenge."""
    _require_developer(current_user)

    row = fetch_one(
        "SELECT * FROM challenge_feedback WHERE user_id = ? AND challenge_id = ?",
        (current_user["id"], challenge_id),
    )
    if row is None:
        return None
    return ChallengeFeedbackResponse(**row)


@router.get("/challenges/{challenge_id}/feedback/summary", response_model=ChallengeFeedbackSummary)
def get_challenge_feedback_summary(
    challenge_id: str,
    current_user: CurrentUser,
) -> ChallengeFeedbackSummary:
    """Get aggregate feedback ratings for a challenge."""
    challenge = fetch_one("SELECT id FROM challenges WHERE id = ?", (challenge_id,))
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    row = fetch_one(
        """SELECT
             ? AS challenge_id,
             ROUND(AVG(rating_overall), 2) AS avg_overall,
             ROUND(AVG(rating_difficulty), 2) AS avg_difficulty,
             ROUND(AVG(rating_clarity), 2) AS avg_clarity,
             COUNT(*) AS total_count
           FROM challenge_feedback
           WHERE challenge_id = ?""",
        (challenge_id, challenge_id),
    )
    return ChallengeFeedbackSummary(**row)


# ── Platform Feedback ───────────────────────────────────────────────


@router.post("/feedback/platform", response_model=PlatformFeedbackResponse, status_code=201)
def create_platform_feedback(
    body: PlatformFeedbackCreate,
    current_user: CurrentUser,
) -> PlatformFeedbackResponse:
    """Submit general platform feedback."""
    feedback_id = secrets.token_hex(16)
    execute(
        """INSERT INTO platform_feedback (id, user_id, category, description, rating, page_url)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            feedback_id,
            current_user["id"],
            body.category,
            body.description,
            body.rating,
            body.page_url,
        ),
    )

    row = fetch_one(
        """SELECT pf.*, u.name AS user_name
           FROM platform_feedback pf
           JOIN users u ON u.id = pf.user_id
           WHERE pf.id = ?""",
        (feedback_id,),
    )
    return PlatformFeedbackResponse(**row)


@router.get("/feedback/platform/me", response_model=list[PlatformFeedbackResponse])
def list_my_platform_feedback(
    current_user: CurrentUser,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> list[PlatformFeedbackResponse]:
    """List the current user's platform feedback."""
    offset = (page - 1) * limit
    rows = fetch_all(
        """SELECT pf.*, u.name AS user_name
           FROM platform_feedback pf
           JOIN users u ON u.id = pf.user_id
           WHERE pf.user_id = ?
           ORDER BY pf.created_at DESC
           LIMIT ? OFFSET ?""",
        (current_user["id"], limit, offset),
    )
    return [PlatformFeedbackResponse(**r) for r in rows]
