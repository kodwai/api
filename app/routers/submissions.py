from __future__ import annotations

import json
import secrets
import threading

from fastapi import APIRouter, HTTPException, Query, status

from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import CurrentUser
from app.schemas.submission import (
    LocalSubmitRequest,
    StartSubmissionRequest,
    StartSubmissionResponse,
    SubmissionResponse,
)

router = APIRouter(tags=["submissions"])


def _row_to_response(row: dict) -> SubmissionResponse:
    data = dict(row)
    data["score_breakdown"] = json.loads(data["score_breakdown"]) if data.get("score_breakdown") else None
    return SubmissionResponse(**data)


def _require_developer(user: dict) -> None:
    if user.get("user_type") != "developer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer account required")


@router.post("/challenges/{challenge_id}/start", response_model=StartSubmissionResponse, status_code=201)
def start_challenge(challenge_id: str, current_user: CurrentUser) -> StartSubmissionResponse:
    """Start a challenge — creates a submission record, returns full challenge config."""
    _require_developer(current_user)

    # Fetch challenge (by id or slug)
    challenge = fetch_one(
        "SELECT * FROM challenges WHERE (id = ? OR slug = ?) AND is_public = 1",
        (challenge_id, challenge_id),
    )
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    # Create submission
    submission_id = secrets.token_hex(16)
    execute(
        """INSERT INTO submissions (id, challenge_id, user_id, status, mode, started_at)
           VALUES (?, ?, ?, 'in_progress', 'local', datetime('now'))""",
        (submission_id, challenge["id"], current_user["id"]),
    )

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

    # Check if time limit exceeded
    challenge = fetch_one("SELECT time_limit_minutes FROM challenges WHERE id = ?", (submission["challenge_id"],))
    time_limit_ms = (challenge["time_limit_minutes"] if challenge else 60) * 60 * 1000
    is_over_time = body.time_taken_ms > time_limit_ms if body.time_taken_ms else False

    # Store submission data
    code_json = json.dumps([{"path": f.path, "content": f.content} for f in body.code_snapshot])
    git_log_json = json.dumps(body.git_log) if body.git_log else None
    test_results_json = json.dumps(body.test_results.model_dump()) if body.test_results else None
    agent_trace_json = json.dumps(body.agent_trace) if body.agent_trace else None

    execute(
        """UPDATE submissions SET
              status = 'submitted',
              code_snapshot = ?,
              git_diff = ?,
              git_log = ?,
              test_results = ?,
              agent_used = ?,
              agent_trace = ?,
              time_taken_ms = ?,
              submitted_at = datetime('now'),
              updated_at = datetime('now')
           WHERE id = ?""",
        (
            code_json, body.git_diff, git_log_json, test_results_json,
            body.agent_used, agent_trace_json, body.time_taken_ms,
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


    # Old _score_submission placeholder removed — using app.services.challenge_scoring
