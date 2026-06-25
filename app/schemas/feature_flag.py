from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class FeatureFlagCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    enabled: bool = True
    starts_at: Optional[str] = None  # ISO-8601 or null
    ends_at: Optional[str] = None


class FeatureFlagUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = None
    enabled: Optional[bool] = None
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
