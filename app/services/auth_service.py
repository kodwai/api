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
    organization_name: str,
    client_url: str,
) -> dict[str, Any]:
    """Register a new user and organization.

    Creates the organization first, then the admin user, and sends
    a verification email.

    Returns:
        A dict with 'access_token' and 'user'.
    """
    # Check if email already taken
    existing = fetch_one("SELECT id FROM users WHERE email = ?", (email,))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create organization
    org_id = secrets.token_hex(16)
    execute(
        "INSERT INTO organizations (id, name) VALUES (?, ?)",
        (org_id, organization_name),
    )

    # Create user
    user_id = secrets.token_hex(16)
    password_hash = hash_password(password)
    email_verification_token = secrets.token_hex(32)

    execute(
        """INSERT INTO users (id, email, password_hash, name, role, organization_id, email_verification_token)
           VALUES (?, ?, ?, ?, 'admin', ?, ?)""",
        (user_id, email, password_hash, name, org_id, email_verification_token),
    )

    # Send verification email (fire and forget)
    send_verification_email(email, email_verification_token, client_url)

    # Create access token
    access_token = create_access_token({"sub": user_id})

    user = fetch_one(
        "SELECT id, email, name, role, organization_id, email_verified, created_at FROM users WHERE id = ?",
        (user_id,),
    )

    return {"access_token": access_token, "user": user}


def login(email: str, password: str) -> dict[str, Any]:
    """Authenticate a user with email and password.

    Returns:
        A dict with 'access_token' and 'user'.
    """
    user = fetch_one(
        "SELECT id, email, password_hash, name, role, organization_id, email_verified, created_at FROM users WHERE email = ?",
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
        "SELECT id, email, name, role, organization_id, email_verified, created_at FROM users WHERE id = ?",
        (user["id"],),
    )
    return updated_user  # type: ignore[return-value]
