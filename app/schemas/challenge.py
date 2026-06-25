from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChallengeCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    problem_statement_md: str = Field(..., min_length=1)
    difficulty: str = Field(..., pattern=r"^(easy|medium|hard)$")
    category: str = Field(..., min_length=1, max_length=100)
    tags: list[str] = Field(default_factory=list)
    time_limit_minutes: int = Field(default=60, ge=5, le=480)
    test_suite: Optional[list[dict]] = None
    scoring_config: dict = Field(default_factory=dict)
    starter_files: Optional[list[dict]] = None
    allowed_tools: Optional[list[str]] = None
    disallowed_tools: Optional[list[str]] = None
    max_budget_usd: Optional[float] = None
    is_public: bool = True
    is_featured: bool = False


class ChallengeUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    problem_statement_md: Optional[str] = None
    difficulty: Optional[str] = Field(default=None, pattern=r"^(easy|medium|hard)$")
    category: Optional[str] = Field(default=None, max_length=100)
    tags: Optional[list[str]] = None
    time_limit_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    test_suite: Optional[list[dict]] = None
    scoring_config: Optional[dict] = None
    starter_files: Optional[list[dict]] = None
    allowed_tools: Optional[list[str]] = None
    disallowed_tools: Optional[list[str]] = None
    max_budget_usd: Optional[float] = None
    is_public: Optional[bool] = None
    is_featured: Optional[bool] = None


class ChallengeResponse(BaseModel):
    id: str
    title: str
    slug: str
    description: str
    problem_statement_md: Optional[str] = None  # Hidden until started
    difficulty: str
    category: str
    tags: list[str] = Field(default_factory=list)
    time_limit_minutes: int
    test_suite: Optional[list[dict]] = None
    scoring_config: dict = Field(default_factory=dict)
    starter_files: Optional[list[dict]] = None
    allowed_tools: Optional[list[str]] = None
    disallowed_tools: Optional[list[str]] = None
    max_budget_usd: Optional[float] = None
    is_public: bool
    is_featured: bool
    submission_count: int = 0
    avg_score: Optional[float] = None
    created_at: str
    updated_at: str


class ChallengeListResponse(BaseModel):
    id: str
    title: str
    slug: str
    description: str
    difficulty: str
    category: str
    tags: list[str] = Field(default_factory=list)
    time_limit_minutes: int
    is_featured: bool
    submission_count: int = 0
    avg_score: Optional[float] = None


class CategoryCount(BaseModel):
    category: str
    count: int
