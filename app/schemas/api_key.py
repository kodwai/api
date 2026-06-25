from __future__ import annotations

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    key: str = Field(..., min_length=10, description="Anthropic API key")
    label: str = Field(default="Default", max_length=255, description="Optional label for the key")


class ApiKeyResponse(BaseModel):
    id: str
    label: str
    key_last4: str
    is_active: bool
    created_at: str
