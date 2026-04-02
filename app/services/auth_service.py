from __future__ import annotations

import secrets
from typing import Any

from fastapi import HTTPException, status

from app.core.database import execute, fetch_one
from app.core.security import create_access_token, hash_password, verify_password
from app.services.email_service import send_verification_email


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
