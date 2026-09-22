from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.automation_tokens import DEFAULT_EXPIRES_DAYS, MAX_EXPIRES_DAYS


class AutomationTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    scopes: list[str] = Field(..., min_length=1)
    expires_days: int = Field(DEFAULT_EXPIRES_DAYS, ge=1, le=MAX_EXPIRES_DAYS)
