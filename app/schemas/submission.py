from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StartSubmissionRequest(BaseModel):
    challenge_id: str


class StartSubmissionResponse(BaseModel):
    submission_id: str
    challenge: dict  # Full challenge config including problem_statement_md, starter_files, test_suite


class FileSnapshot(BaseModel):
    path: str
    content: str


class TestResults(BaseModel):
    passed: int = 0
    failed: int = 0
    total: int = 0
    output: str = ""


class LocalSubmitRequest(BaseModel):
    code_snapshot: list[FileSnapshot] = Field(default_factory=list)
    git_diff: Optional[str] = None
    git_log: Optional[list[dict]] = None
    test_results: Optional[TestResults] = None
    agent_used: Optional[str] = None
    model_raw: Optional[str] = None
    model_provider: Optional[str] = None
    agent_trace: Optional[dict] = None
    time_taken_ms: int = 0


class SubmissionResponse(BaseModel):
    id: str
    challenge_id: str
    user_id: str
    status: str
    mode: str
    agent_used: Optional[str] = None
    model: Optional[str] = None
    model_display: Optional[str] = None
    score: Optional[float] = None
    score_breakdown: Optional[dict] = None
    time_taken_ms: Optional[int] = None
    started_at: str
    submitted_at: Optional[str] = None
    scored_at: Optional[str] = None
    created_at: str
    # Joined fields
    challenge_title: Optional[str] = None
    challenge_slug: Optional[str] = None
    challenge_difficulty: Optional[str] = None
    challenge_time_limit_minutes: Optional[int] = None
