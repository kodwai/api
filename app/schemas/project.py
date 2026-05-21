from __future__ import annotations

from pydantic import BaseModel, Field


class RubricDimension(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    weight: int = Field(..., ge=1, le=10)
    description: str = Field(..., min_length=1)


class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    problem_statement_md: str = Field(..., min_length=1)
    time_limit_minutes: int = Field(default=60, ge=1)
    difficulty: str | None = Field(default=None, pattern="^(easy|medium|hard)$")
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    rubric: list[RubricDimension] = Field(default_factory=list)
    max_budget_usd: float | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    problem_statement_md: str | None = Field(default=None, min_length=1)
    time_limit_minutes: int | None = Field(default=None, ge=1)
    difficulty: str | None = Field(default=None, pattern="^(easy|medium|hard)$")
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    rubric: list[RubricDimension] | None = None
    max_budget_usd: float | None = None


class ProjectResponse(BaseModel):
    id: str
    organization_id: str
    title: str
    description: str | None = None
    problem_statement_md: str
    time_limit_minutes: int
    difficulty: str | None = None
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    rubric: list[RubricDimension]
    max_budget_usd: float | None = None
    is_archived: bool
    created_at: str
    updated_at: str
