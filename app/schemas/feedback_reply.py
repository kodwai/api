from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class FeedbackReplyRequest(BaseModel):
    """Body of POST /api/admin/feedback/{platform|challenges}/{id}/reply."""

    message: str = Field(..., min_length=1, max_length=5000)
    send_email: bool = True
    # Platform feedback only: challenge_feedback has no status column.
    status: Optional[str] = Field(default="resolved", pattern=r"^(new|reviewed|resolved|dismissed)$")
    dry_run: bool = False

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value
