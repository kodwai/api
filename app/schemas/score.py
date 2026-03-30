from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreDimension(BaseModel):
    name: str
    score: float = Field(ge=0, le=10)
    max_score: float = 10
    justification: str = ""


class ScoreCreate(BaseModel):
    """For manual scores."""

    dimensions: list[ScoreDimension]
    overall_score: float = Field(ge=0, le=10)
    summary: str | None = None


class ScoreResponse(BaseModel):
    id: str
    session_id: str
    score_type: str  # "ai" or "manual"
    scorer_id: str | None = None
    dimensions: list[ScoreDimension]
    overall_score: float
    summary: str | None = None
    strengths: list[str] | None = None
    weaknesses: list[str] | None = None
    created_at: str


class CommentCreate(BaseModel):
    content: str = Field(min_length=1)
    event_id: str | None = None  # optional, to attach to a specific event


class CommentResponse(BaseModel):
    id: str
    session_id: str
    user_id: str
    user_name: str | None = None
    event_id: str | None = None
    content: str
    created_at: str
