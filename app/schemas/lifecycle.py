from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class LifecycleRunRequest(BaseModel):
    """POST /api/admin/lifecycle/run. Dry run unless dry_run is explicitly false."""
    dry_run: bool = True
    limit: int = Field(default=50, ge=1, le=500)
    templates: Optional[list[str]] = Field(default=None, max_length=20)
    run_id: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")


class LifecycleRunItem(BaseModel):
    user_id: str
    masked_email: str
    template: str
    reason: Optional[str] = None
    status: str
    subject: Optional[str] = None
    email_send_id: Optional[str] = None
    error: Optional[str] = None


class LifecycleRunResponse(BaseModel):
    run_id: str
    dry_run: bool
    refused_reason: Optional[str] = None
    items: list[LifecycleRunItem]
    counts: dict[str, int] = {}
    limit_reached: bool = False


class LifecyclePreviewResponse(BaseModel):
    template: str
    subject: str
    text: str
    html: str


class EmailSendItem(BaseModel):
    id: str
    user_id: Optional[str] = None
    masked_email: str
    template: str
    stream: str
    status: str
    created_at: str
    sent_at: Optional[str] = None
    error: Optional[str] = None


class EmailSendsResponse(BaseModel):
    items: list[EmailSendItem]
