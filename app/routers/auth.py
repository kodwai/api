from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.deps import CurrentUser
from app.schemas.auth import (
    CliAuthorizeResponse,
    CliTokenRequest,
    ForgotPasswordRequest,
    GitHubCallbackRequest,
    LoginRequest,
    PasswordUpdateRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
    UsernameUpdateRequest,
)
from app.services import auth_service, entitlement_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_response(user: dict) -> UserResponse:
    """Build a UserResponse enriched with API-key, entitlement, and welcome state.

    Single source so every endpoint returning the current user stays consistent
    (notably can_submit, which the web app and CLI gate on).
    """
    return UserResponse(**{
        **user,
        "has_claude_api_key": auth_service.has_claude_api_key(user),
        "welcomed": auth_service.has_welcomed(user),
        **entitlement_service.get_entitlement(user),
    })


@router.post("/signup", status_code=201)
def signup(body: SignupRequest) -> dict:
    """Register a new user. Company users get an organization; developers do not."""
    result = auth_service.signup(
        email=body.email,
        password=body.password,
        name=body.name,
        user_type=body.user_type,
        organization_name=body.organization_name,
        client_url=settings.CLIENT_URL,
    )
    return result


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest) -> TokenResponse:
    """Authenticate with email and password."""
    result = auth_service.login(email=body.email, password=body.password)
    return TokenResponse(access_token=result["access_token"])


@router.post("/logout", status_code=204)
def logout():
    """Logout (client-side token removal). Endpoint kept for API completeness."""
    return None


@router.get("/verify-email", response_model=UserResponse)
def verify_email(token: str = Query(..., description="Email verification token")) -> UserResponse:
    """Verify a user's email address."""
    return _user_response(auth_service.verify_email(token))


@router.get("/me", response_model=UserResponse)
def get_me(current_user: CurrentUser) -> UserResponse:
    """Get the current authenticated user, including free-submission entitlement."""
    return _user_response(current_user)


@router.post("/me/welcome", status_code=204)
def mark_welcome(current_user: CurrentUser):
    """Mark the first-login welcome intro as seen for the current developer."""
    auth_service.mark_welcomed(current_user["id"])
    return None


@router.patch("/me/username", response_model=UserResponse)
def update_username(body: UsernameUpdateRequest, current_user: CurrentUser) -> UserResponse:
    """Update the current user's username."""
    return _user_response(auth_service.update_username(current_user["id"], body.username))


@router.patch("/me/password", status_code=204)
def update_password(body: PasswordUpdateRequest, current_user: CurrentUser):
    """Change the current user's password after verifying the current one."""
    auth_service.update_password(current_user["id"], body.current_password, body.new_password)
    return None


@router.post("/forgot-password", status_code=204)
def forgot_password(body: ForgotPasswordRequest):
    """Issue a password reset token and email it. Always returns 204 to avoid account enumeration."""
    auth_service.request_password_reset(email=body.email, client_url=settings.CLIENT_URL)
    return None


@router.post("/reset-password", status_code=204)
def reset_password(body: ResetPasswordRequest):
    """Consume a reset token and set a new password."""
    auth_service.reset_password(token=body.token, new_password=body.password)
    return None


@router.post("/cli/authorize", response_model=CliAuthorizeResponse)
def cli_authorize(current_user: CurrentUser) -> CliAuthorizeResponse:
    """Issue a one-time authorization code for a CLI device (loopback login flow).

    Requires an authenticated web session: the logged-in user is approving a CLI
    sign-in on this machine. The CLI exchanges the returned code via /cli/token.
    """
    result = auth_service.create_cli_auth_code(current_user["id"])
    return CliAuthorizeResponse(**result)


@router.post("/cli/token")
def cli_token(body: CliTokenRequest) -> dict:
    """Exchange a one-time CLI authorization code for an access token."""
    return auth_service.exchange_cli_auth_code(body.code)


@router.get("/github")
def github_authorize() -> RedirectResponse:
    """Redirect to GitHub OAuth consent screen."""
    params = urlencode({
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": f"{settings.CLIENT_URL}/auth/github/callback",
        "scope": "read:user user:email",
    })
    return RedirectResponse(url=f"https://github.com/login/oauth/authorize?{params}")


@router.post("/github/callback")
def github_callback(body: GitHubCallbackRequest) -> dict:
    """Exchange GitHub OAuth code for a Kodwai access token."""
    return auth_service.github_login(code=body.code)
