from __future__ import annotations

import json
import secrets
import threading

from fastapi import APIRouter, HTTPException, Query, status

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import CurrentUser
from app.schemas.submission import (
    LocalSubmitRequest,
    StartSubmissionRequest,
    StartSubmissionResponse,
    SubmissionResponse,
)
from app.services import entitlement_service
from app.services.model_registry import normalize_model

router = APIRouter(tags=["submissions"])


def _row_to_response(row: dict) -> SubmissionResponse:
    data = dict(row)
    data["score_breakdown"] = json.loads(data["score_breakdown"]) if data.get("score_breakdown") else None
    return SubmissionResponse(**data)


def _require_developer(user: dict) -> None:
    if user.get("user_type") != "developer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account required")


def _active_challenge_detail(title: str | None = None) -> str:
    """Message shown when a developer tries to start a second concurrent challenge."""
    name = f': "{title}"' if title else ""
    return (
        f"You already have a challenge in progress{name}. "
        f"Submit it, or stop it in the app, before starting another: {settings.CLIENT_URL}/dev/submissions"
    )


def _no_credits_detail() -> str:
    """Message shown when a developer cannot submit (no free credits and no own key).

    Phrased to be accurate whether they exhausted a free tier or the free tier
    was never available.
    """
    return f"Connect your Anthropic API key to submit challenges: {settings.CLIENT_URL}"


@router.post("/challenges/{challenge_id}/start", response_model=StartSubmissionResponse, status_code=201)
def start_challenge(challenge_id: str, current_user: CurrentUser) -> StartSubmissionResponse:
    """Start a challenge — creates a submission record, returns full challenge config."""
    _require_developer(current_user)

    # One challenge at a time: block if the developer already has one in progress.
    active = fetch_one(
        """SELECT c.title FROM submissions s JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'in_progress' ORDER BY s.created_at DESC LIMIT 1""",
        (current_user["id"],),
    )
    if active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_active_challenge_detail(active["title"]))

    # Gate: don't let a developer start a challenge they won't be able to submit.
    if not entitlement_service.get_entitlement(current_user)["can_submit"]:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=_no_credits_detail())

    # Fetch challenge (by id or slug)
    challenge = fetch_one(
        "SELECT * FROM challenges WHERE (id = ? OR slug = ?) AND is_public = 1",
        (challenge_id, challenge_id),
    )
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    # Create submission. The partial unique index (one in_progress per user) is the
    # authoritative guard: if two starts race past the check above, the second INSERT
    # fails here and we surface the same conflict.
    submission_id = secrets.token_hex(16)
    try:
        execute(
            """INSERT INTO submissions (id, challenge_id, user_id, status, mode, started_at)
               VALUES (?, ?, ?, 'in_progress', 'local', datetime('now'))""",
            (submission_id, challenge["id"], current_user["id"]),
        )
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_active_challenge_detail()) from e
        raise

    # Return full challenge config (including problem statement, starter files, test suite)
    challenge_config = {
        "id": challenge["id"],
        "title": challenge["title"],
        "slug": challenge["slug"],
        "problem_statement_md": challenge["problem_statement_md"],
        "difficulty": challenge["difficulty"],
        "category": challenge["category"],
        "tags": json.loads(challenge["tags"]) if challenge.get("tags") else [],
        "time_limit_minutes": challenge["time_limit_minutes"],
        "starter_files": json.loads(challenge["starter_files"]) if challenge.get("starter_files") else None,
        "test_suite": json.loads(challenge["test_suite"]) if challenge.get("test_suite") else None,
        "scoring_config": json.loads(challenge["scoring_config"]) if challenge.get("scoring_config") else {},
    }

    return StartSubmissionResponse(submission_id=submission_id, challenge=challenge_config)


@router.post("/submissions/{submission_id}/submit", response_model=SubmissionResponse)
def submit_solution(submission_id: str, body: LocalSubmitRequest, current_user: CurrentUser) -> SubmissionResponse:
    """Submit a local mode solution for scoring."""
    _require_developer(current_user)

    submission = fetch_one(
        "SELECT * FROM submissions WHERE id = ? AND user_id = ?",
        (submission_id, current_user["id"]),
    )
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    if submission["status"] != "in_progress":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Submission already submitted")

    # Decide whose Anthropic key pays for AI scoring and reserve a free credit if
    # this is a platform-funded submission. Refuse if the developer has neither an
    # own key nor a remaining free credit.
    key_source = entitlement_service.decide_key_source(current_user)
    if key_source is None:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=_no_credits_detail())
    # Permanently spend a free credit now (deleting the submission later won't refund it).
    if key_source == entitlement_service.KEY_SOURCE_PLATFORM:
        entitlement_service.consume_free_credit(current_user["id"])

    # Check if time limit exceeded
    challenge = fetch_one("SELECT time_limit_minutes FROM challenges WHERE id = ?", (submission["challenge_id"],))
    time_limit_ms = (challenge["time_limit_minutes"] if challenge else 60) * 60 * 1000
    is_over_time = body.time_taken_ms > time_limit_ms if body.time_taken_ms else False

    # Store submission data
    code_json = json.dumps([{"path": f.path, "content": f.content} for f in body.code_snapshot])
    git_log_json = json.dumps(body.git_log) if body.git_log else None
    test_results_json = json.dumps(body.test_results.model_dump()) if body.test_results else None
    agent_trace_json = json.dumps(body.agent_trace) if body.agent_trace else None
    norm = normalize_model(body.model_raw, body.model_provider)
    model_slug = norm["slug"] if norm else None
    model_display = norm["display"] if norm else None
    model_provider = norm["provider"] if norm else None

    execute(
        """UPDATE submissions SET
              status = 'submitted',
              code_snapshot = ?,
              git_diff = ?,
              git_log = ?,
              test_results = ?,
              agent_used = ?,
              agent_trace = ?,
              model = ?,
              model_display = ?,
              model_provider = ?,
              time_taken_ms = ?,
              key_source = ?,
              submitted_at = datetime('now'),
              updated_at = datetime('now')
           WHERE id = ?""",
        (
            code_json, body.git_diff, git_log_json, test_results_json,
            body.agent_used, agent_trace_json,
            model_slug, model_display, model_provider,
            body.time_taken_ms,
            key_source,
            submission_id,
        ),
    )

    # Trigger scoring in background
    execute("UPDATE submissions SET status = 'scoring' WHERE id = ?", (submission_id,))
    from app.services.challenge_scoring import score_submission
    threading.Thread(target=score_submission, args=(submission_id,), daemon=True).start()

    row = fetch_one(
        """SELECT s.*, c.title as challenge_title, c.slug as challenge_slug, c.difficulty as challenge_difficulty, c.time_limit_minutes as challenge_time_limit_minutes
           FROM submissions s JOIN challenges c ON s.challenge_id = c.id
           WHERE s.id = ?""",
        (submission_id,),
    )
    return _row_to_response(row)  # type: ignore[arg-type]


@router.get("/submissions/me", response_model=list[SubmissionResponse])
def list_my_submissions(
    current_user: CurrentUser,
    challenge_id: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> list[SubmissionResponse]:
    """List current developer's submissions. Optionally filter by challenge_id."""
    _require_developer(current_user)

    offset = (page - 1) * limit

    if challenge_id:
        rows = fetch_all(
            """SELECT s.*, c.title as challenge_title, c.slug as challenge_slug, c.difficulty as challenge_difficulty, c.time_limit_minutes as challenge_time_limit_minutes
               FROM submissions s JOIN challenges c ON s.challenge_id = c.id
               WHERE s.user_id = ? AND s.challenge_id = ?
               ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",
            (current_user["id"], challenge_id, limit, offset),
        )
    else:
        rows = fetch_all(
            """SELECT s.*, c.title as challenge_title, c.slug as challenge_slug, c.difficulty as challenge_difficulty, c.time_limit_minutes as challenge_time_limit_minutes
               FROM submissions s JOIN challenges c ON s.challenge_id = c.id
               WHERE s.user_id = ?
               ORDER BY s.created_at DESC LIMIT ? OFFSET ?""",
            (current_user["id"], limit, offset),
        )
    return [_row_to_response(row) for row in rows]


# Declared before "/submissions/{submission_id}" so "active" isn't matched as an id.
@router.get("/submissions/active", response_model=SubmissionResponse | None)
def get_active_submission(current_user: CurrentUser) -> SubmissionResponse | None:
    """Return the developer's in-progress challenge (one at a time), or null if none."""
    _require_developer(current_user)
    row = fetch_one(
        """SELECT s.*, c.title as challenge_title, c.slug as challenge_slug, c.difficulty as challenge_difficulty, c.time_limit_minutes as challenge_time_limit_minutes
           FROM submissions s JOIN challenges c ON s.challenge_id = c.id
           WHERE s.user_id = ? AND s.status = 'in_progress'
           ORDER BY s.created_at DESC LIMIT 1""",
        (current_user["id"],),
    )
    return _row_to_response(row) if row else None


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
def get_submission(submission_id: str, current_user: CurrentUser) -> SubmissionResponse:
    """Get a submission's details and score."""
    _require_developer(current_user)

    row = fetch_one(
        """SELECT s.*, c.title as challenge_title, c.slug as challenge_slug, c.difficulty as challenge_difficulty, c.time_limit_minutes as challenge_time_limit_minutes
           FROM submissions s JOIN challenges c ON s.challenge_id = c.id
           WHERE s.id = ? AND s.user_id = ?""",
        (submission_id, current_user["id"]),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    return _row_to_response(row)


@router.delete("/submissions/{submission_id}", status_code=204)
def delete_submission(submission_id: str, current_user: CurrentUser):
    """Stop an in-progress challenge or delete a finished submission (owner only).

    Recomputes the leaderboard, challenge, and profile stats so nothing stale is
    left behind. Refuses while a submission is mid-scoring to avoid racing the
    background scorer.
    """
    _require_developer(current_user)

    submission = fetch_one(
        "SELECT * FROM submissions WHERE id = ? AND user_id = ?",
        (submission_id, current_user["id"]),
    )
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    if submission["status"] in ("submitted", "scoring"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This submission is being scored. Try again in a few seconds.",
        )

    from app.services import submission_service
    submission_service.delete_submission(submission)
    return None


    # Old _score_submission placeholder removed — using app.services.challenge_scoring
