from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.schemas.project import RubricDimension


class SessionCreate(BaseModel):
    project_id: str = Field(..., min_length=1)
    api_key_id: str = Field(..., min_length=1)
    candidate_name: str = Field(..., min_length=1, max_length=255)
    candidate_email: EmailStr
    max_budget_usd: float | None = None


class SessionResponse(BaseModel):
    id: str
    project_id: str
    api_key_id: str
    organization_id: str
    candidate_name: str
    candidate_email: str
    status: str
    session_token: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    end_reason: str | None = None
    total_cost_usd: float | None = None
    total_tokens: int | None = None
    max_budget_usd: float | None = None
    created_at: str
    updated_at: str
    project_title: str | None = None
    overall_score: float | None = None


class SessionConfigResponse(BaseModel):
    """Returned to the CLI when it starts a session."""

    session_id: str
    session_token: str
    webhook_secret: str
    api_key: str  # session token (used as API key for proxy auth)
    proxy_base_url: str  # URL for ANTHROPIC_BASE_URL
    project_title: str
    problem_statement_md: str
    time_limit_minutes: int
    difficulty: str | None = None
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    rubric: list[RubricDimension]
    max_budget_usd: float | None = None
    starter_files: str | None = None


class SessionEventCreate(BaseModel):
    event_type: str = Field(..., min_length=1)
    data: dict | None = None
    timestamp: str | None = None


class SessionFileChange(BaseModel):
    file_path: str = Field(..., min_length=1)
    content: str
    change_type: str = Field(..., pattern="^(create|update|delete)$")
    timestamp: str | None = None


class SessionEndRequest(BaseModel):
    end_reason: str = Field(default="completed")
    total_cost_usd: float | None = None
    total_tokens: int | None = None
    final_files: list[SessionFileChange] | None = None
