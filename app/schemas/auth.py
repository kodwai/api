from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    user_type: Literal["developer", "company"] = "company"
    # Company-only
    organization_name: Optional[str] = Field(default=None, max_length=255)
    # Developer-only
    username: Optional[str] = Field(default=None, min_length=3, max_length=50)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GitHubCallbackRequest(BaseModel):
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    user_type: str
    organization_id: Optional[str] = None
    username: Optional[str] = None
    email_verified: bool
    created_at: str
