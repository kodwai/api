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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GitHubCallbackRequest(BaseModel):
    code: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10)
    password: str = Field(..., min_length=8, max_length=128)


class UsernameUpdateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)


class PasswordUpdateRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CliAuthorizeResponse(BaseModel):
    """Response when the web app mints a one-time CLI authorization code."""
    code: str
    expires_in: int


class CliTokenRequest(BaseModel):
    """CLI exchanges a one-time authorization code for an access token."""
    code: str = Field(..., min_length=10)


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    user_type: str
    organization_id: Optional[str] = None
    username: Optional[str] = None
    email_verified: bool
    has_claude_api_key: bool = False
    created_at: str
