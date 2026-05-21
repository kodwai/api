from __future__ import annotations

import logging
import secrets
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.database import execute, fetch_one
from app.core.security import create_access_token, hash_password, verify_password
from app.services.default_projects import seed_for_organization
from app.services.email_service import send_verification_email

logger = logging.getLogger(__name__)


def signup(
    email: str,
    password: str,
    name: str,
    user_type: str = "company",
    organization_name: str | None = None,
    username: str | None = None,
    client_url: str = "",
) -> dict[str, Any]:
    """Register a new user. Company users get an organization; developer users do not."""
    # Check if email already taken
    existing = fetch_one("SELECT id FROM users WHERE email = ?", (email,))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user_id = secrets.token_hex(16)
    password_hash = hash_password(password)
    email_verification_token = secrets.token_hex(32)

    if user_type == "company":
        if not organization_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization_name is required for company accounts",
            )
        # Create organization
        org_id = secrets.token_hex(16)
        execute(
            "INSERT INTO organizations (id, name) VALUES (?, ?)",
            (org_id, organization_name),
        )
        execute(
            """INSERT INTO users (id, email, password_hash, name, role, organization_id, user_type, email_verification_token)
               VALUES (?, ?, ?, ?, 'admin', ?, 'company', ?)""",
            (user_id, email, password_hash, name, org_id, email_verification_token),
        )
        seed_for_organization(org_id)
    else:
        # Developer signup — no org
        if not username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="username is required for developer accounts",
            )
        # Check username uniqueness
        existing_username = fetch_one("SELECT id FROM users WHERE username = ?", (username,))
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already taken",
            )
        execute(
            """INSERT INTO users (id, email, password_hash, name, username, role, organization_id, user_type, email_verification_token)
               VALUES (?, ?, ?, ?, ?, 'admin', NULL, 'developer', ?)""",
            (user_id, email, password_hash, name, username, email_verification_token),
        )
        # Create developer profile
        profile_id = secrets.token_hex(16)
        execute(
            "INSERT INTO developer_profiles (id, user_id) VALUES (?, ?)",
            (profile_id, user_id),
        )

    # Send verification email
    send_verification_email(email, email_verification_token, client_url)

    return {"message": "Account created. Please check your email to verify your account."}


def login(email: str, password: str) -> dict[str, Any]:
    """Authenticate a user with email and password.

    Returns:
        A dict with 'access_token' and 'user'.
    """
    user = fetch_one(
        "SELECT id, email, password_hash, name, role, organization_id, user_type, username, email_verified, created_at FROM users WHERE email = ?",
        (email,),
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user["email_verified"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before signing in. Check your inbox for the verification link.",
        )

    access_token = create_access_token({"sub": user["id"]})

    # Remove password_hash from response
    user_response = {k: v for k, v in user.items() if k != "password_hash"}

    return {"access_token": access_token, "user": user_response}


def verify_email(token: str) -> dict[str, Any]:
    """Verify a user's email using the verification token.

    Returns:
        The updated user dict.
    """
    user = fetch_one(
        "SELECT id, email FROM users WHERE email_verification_token = ?",
        (token,),
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )

    execute(
        "UPDATE users SET email_verified = 1, email_verification_token = NULL WHERE id = ?",
        (user["id"],),
    )

    updated_user = fetch_one(
        "SELECT id, email, name, role, organization_id, user_type, username, email_verified, created_at FROM users WHERE id = ?",
        (user["id"],),
    )
    return updated_user  # type: ignore[return-value]


def github_login(code: str) -> dict[str, Any]:
    """Exchange a GitHub OAuth code for a Kodwai access token.

    If the GitHub user already exists (by github_id), log them in.
    If the email matches an existing account, link the GitHub ID.
    Otherwise, create a new developer account.
    """
    try:
        return _github_login_inner(code)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("GitHub OAuth error: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"GitHub OAuth error: {e}")


def _github_login_inner(code: str) -> dict[str, Any]:
    # Exchange code for GitHub access token
    token_resp = httpx.post(
        "https://github.com/login/oauth/access_token",
        json={
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
        },
        headers={"Accept": "application/json"},
        timeout=10,
    )
    if token_resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="GitHub OAuth failed")

    token_data = token_resp.json()
    gh_access_token = token_data.get("access_token")
    if not gh_access_token:
        error = token_data.get("error_description", "Failed to get access token from GitHub")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

    # Fetch GitHub user profile
    gh_headers = {"Authorization": f"Bearer {gh_access_token}", "Accept": "application/json"}
    user_resp = httpx.get("https://api.github.com/user", headers=gh_headers, timeout=10)
    if user_resp.status_code != 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to fetch GitHub profile")

    gh_user = user_resp.json()
    gh_id = str(gh_user["id"])
    gh_username = gh_user.get("login", "")
    gh_name = gh_user.get("name") or gh_username
    gh_avatar = gh_user.get("avatar_url")
    gh_email = gh_user.get("email")

    # If GitHub doesn't expose email publicly, fetch from emails API
    if not gh_email:
        emails_resp = httpx.get("https://api.github.com/user/emails", headers=gh_headers, timeout=10)
        if emails_resp.status_code == 200:
            for em in emails_resp.json():
                if em.get("primary") and em.get("verified"):
                    gh_email = em["email"]
                    break

    if not gh_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No verified email found on your GitHub account. Please add a verified email to GitHub and try again.",
        )

    # Check if user exists by github_id
    existing = fetch_one(
        "SELECT id, email, name, role, organization_id, user_type, username, email_verified, is_banned, banned_reason, created_at FROM users WHERE github_id = ?",
        (gh_id,),
    )

    if existing:
        if existing.get("is_banned"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Account banned: {existing.get('banned_reason', 'Account suspended')}")
        # Update avatar on each login
        execute("UPDATE users SET avatar_url = ? WHERE id = ?", (gh_avatar, existing["id"]))
        access_token = create_access_token({"sub": existing["id"]})
        user_response = {k: v for k, v in existing.items() if k not in ("password_hash", "is_banned", "banned_reason")}
        return {"access_token": access_token, "user": user_response}

    # Check if email matches existing account — link GitHub
    existing_by_email = fetch_one(
        "SELECT id, email, name, role, organization_id, user_type, username, email_verified, is_banned, banned_reason, created_at FROM users WHERE email = ?",
        (gh_email,),
    )

    if existing_by_email:
        if existing_by_email.get("is_banned"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Account banned: {existing_by_email.get('banned_reason', 'Account suspended')}")
        # Link GitHub to existing account
        execute(
            "UPDATE users SET github_id = ?, avatar_url = ?, email_verified = 1 WHERE id = ?",
            (gh_id, gh_avatar, existing_by_email["id"]),
        )
        access_token = create_access_token({"sub": existing_by_email["id"]})
        user_response = {k: v for k, v in existing_by_email.items() if k not in ("password_hash", "is_banned", "banned_reason")}
        user_response["email_verified"] = 1
        return {"access_token": access_token, "user": user_response}

    # New user — create developer account
    user_id = secrets.token_hex(16)

    # Ensure username is unique
    base_username = gh_username.lower().replace(" ", "-")
    username = base_username
    suffix = 1
    while fetch_one("SELECT id FROM users WHERE username = ?", (username,)):
        username = f"{base_username}-{suffix}"
        suffix += 1

    execute(
        """INSERT INTO users (id, email, password_hash, name, username, role, organization_id, user_type, github_id, avatar_url, email_verified)
           VALUES (?, ?, '', ?, ?, 'admin', NULL, 'developer', ?, ?, 1)""",
        (user_id, gh_email, gh_name, username, gh_id, gh_avatar),
    )

    # Create developer profile
    profile_id = secrets.token_hex(16)
    execute(
        "INSERT INTO developer_profiles (id, user_id, github_url) VALUES (?, ?, ?)",
        (profile_id, user_id, f"https://github.com/{gh_username}"),
    )

    logger.info("New GitHub OAuth user created: %s (%s)", username, gh_email)

    user = fetch_one(
        "SELECT id, email, name, role, organization_id, user_type, username, email_verified, created_at FROM users WHERE id = ?",
        (user_id,),
    )
    access_token = create_access_token({"sub": user_id})
    return {"access_token": access_token, "user": user}
