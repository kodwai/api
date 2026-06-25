from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class EventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    starts_at: str = Field(..., description="ISO 8601 datetime string")
    ends_at: str = Field(..., description="ISO 8601 datetime string")


class EventResponse(BaseModel):
    id: str
    title: str
    slug: str
    description: str
    starts_at: str
    ends_at: str
    created_by: Optional[str] = None
    is_finalized: bool
    status: str  # "upcoming" | "active" | "ended"
    created_at: str


class EventLeaderboardEntry(BaseModel):
    rank: int
    user_id: str
    name: Optional[str] = None
    username: Optional[str] = None
    score: float
    agent_used: Optional[str] = None
    scored_at: str


class EventWinner(BaseModel):
    id: str
    event_id: str
    user_id: str
    rank: int
    score: float
    awarded_at: str
    # Joined display fields
    name: Optional[str] = None
    username: Optional[str] = None
