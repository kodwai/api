from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.config import settings
from app.core.deps import CurrentUser
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", status_code=201)
def signup(body: SignupRequest) -> dict:
    """Register a new user. Company users get an organization; developers do not."""
    result = auth_service.signup(
        email=body.email,
        password=body.password,
        name=body.name,
        user_type=body.user_type,
        organization_name=body.organization_name,
        username=body.username,
        client_url=settings.CLIENT_URL,
    )
    return result


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    """Authenticate with email and password."""
    result = auth_service.login(email=body.email, password=body.password)
    return TokenResponse(access_token=result["access_token"])


@router.post("/logout", status_code=204)
def logout() -> None:
    """Logout (client-side token removal). Endpoint kept for API completeness."""
    return None


@router.get("/verify-email", response_model=UserResponse)
def verify_email(token: str = Query(..., description="Email verification token")) -> UserResponse:
    """Verify a user's email address."""
    user = auth_service.verify_email(token)
    return UserResponse(**user)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: CurrentUser) -> UserResponse:
    """Get the current authenticated user."""
    return UserResponse(**current_user)
