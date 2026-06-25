from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ── Challenge Feedback ──────────────────────────────────────────────

class ChallengeFeedbackCreate(BaseModel):
    rating_overall: int = Field(..., ge=1, le=5)
    rating_difficulty: Optional[int] = Field(default=None, ge=1, le=5)
    rating_clarity: Optional[int] = Field(default=None, ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=2000)
    submission_id: Optional[str] = None


class ChallengeFeedbackResponse(BaseModel):
    id: str
    challenge_id: str
    user_id: str
    submission_id: Optional[str] = None
    rating_overall: int
    rating_difficulty: Optional[int] = None
    rating_clarity: Optional[int] = None
    comment: Optional[str] = None
    created_at: str
    updated_at: str


class ChallengeFeedbackSummary(BaseModel):
    challenge_id: str
    avg_overall: Optional[float] = None
    avg_difficulty: Optional[float] = None
    avg_clarity: Optional[float] = None
    total_count: int = 0


# ── Platform Feedback ───────────────────────────────────────────────

class PlatformFeedbackCreate(BaseModel):
    category: str = Field(..., pattern=r"^(bug_report|feature_request|general|improvement)$")
    description: str = Field(..., min_length=10, max_length=5000)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    page_url: Optional[str] = Field(default=None, max_length=500)


class PlatformFeedbackResponse(BaseModel):
    id: str
    user_id: str
    user_name: Optional[str] = None
    category: str
    description: str
    rating: Optional[int] = None
    page_url: Optional[str] = None
    status: str
    admin_response: Optional[str] = None
    admin_responded_at: Optional[str] = None
    is_flagged: bool = False
    created_at: str
    updated_at: str


class AdminFeedbackUpdate(BaseModel):
    status: Optional[str] = Field(default=None, pattern=r"^(new|reviewed|resolved|dismissed)$")
    admin_response: Optional[str] = Field(default=None, max_length=5000)
    is_flagged: Optional[bool] = None
