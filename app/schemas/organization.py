from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class OrgCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class OrgUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    logo_url: str | None = None


class OrgResponse(BaseModel):
    id: str
    name: str
    logo_url: str | None = None
    created_at: str


class MemberResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    email_verified: bool
    created_at: str


class MemberRoleUpdate(BaseModel):
    role: str = Field(..., pattern="^(admin|interviewer|viewer)$")


class InvitationCreate(BaseModel):
    email: EmailStr
    role: str = Field(default="interviewer", pattern="^(admin|interviewer|viewer)$")


class InvitationResponse(BaseModel):
    id: str
    email: str
    role: str
    status: str
    invited_by: str
    created_at: str
    expires_at: str
