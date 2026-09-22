from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    user_type: Literal["developer", "company"] = "company"
    # Company-only
    organization_name: Optional[str] = Field(default=None, max_length=255)
    # The unchecked "product news" box. Sets users.marketing_consent_at; onboarding mail ignores it.
    marketing_consent: bool = False


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GitHubCallbackRequest(BaseModel):
    code: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResendVerificationRequest(BaseModel):
    # A plain string, not EmailStr: the route answers 204 for anything, including a malformed
    # address, so the response never says whether the input was even plausible.
    email: str = Field(..., max_length=320)


_ACQUISITION_SOURCE = re.compile(r"^[a-z0-9_-]{1,40}$")
ACQUISITION_PROMPT_MAX_LENGTH = 500


class WelcomeRequest(BaseModel):
    """Optional body for /auth/me/welcome: the "How did you find Kodwai?" answer."""
    # A short slug from the welcome page's list (chatgpt, google, friend, other...).
    acquisition_source: Optional[str] = None
    # Free text: what the developer asked the AI assistant that recommended kodwai.
    acquisition_prompt: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("acquisition_source")
    @classmethod
    def _source(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if not value:
            return None
        if not _ACQUISITION_SOURCE.match(value):
            raise ValueError("acquisition_source must be 1 to 40 lowercase letters, digits, - or _")
        return value

    @field_validator("acquisition_prompt")
    @classmethod
    def _prompt(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.replace("\x00", "").strip()
        if len(value) > ACQUISITION_PROMPT_MAX_LENGTH:
            raise ValueError(f"acquisition_prompt must be at most {ACQUISITION_PROMPT_MAX_LENGTH} characters")
        return value or None


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
    # Free-submission entitlement (developer accounts). can_submit gates the UI:
    # false means free credits are spent and no own key is connected.
    free_submissions_used: int = 0
    free_submissions_limit: int = 0
    free_submissions_remaining: int = 0
    can_submit: bool = True
    # First-login welcome intro: false means the developer hasn't seen it yet.
    welcomed: bool = True
    created_at: str
