from __future__ import annotations

import logging
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.database import execute, fetch_one
from app.core.security import create_access_token, hash_password, verify_password
from app.services import email_templates
from app.services.analytics_events import capture
from app.services.default_projects import seed_for_organization
from app.services.email_service import send_password_reset_email, send_tracked_in_background

logger = logging.getLogger(__name__)


def _generate_unique_username(email: str) -> str:
    """Derive a username from the email local-part and resolve collisions with a numeric suffix."""
    local = email.split("@", 1)[0].lower()
    base = re.sub(r"[^a-z0-9_-]", "", local) or "dev"
    if len(base) < 3:
        base = f"{base}{secrets.token_hex(2)}"
    username = base
    suffix = 1
    while fetch_one("SELECT id FROM users WHERE username = ?", (username,)):
        username = f"{base}-{suffix}"
        suffix += 1
    return username


def has_claude_api_key(user: dict[str, Any]) -> bool:
    """Return True if the user has at least one active Anthropic API key configured."""
    if user.get("user_type") == "developer":
        row = fetch_one(
            "SELECT 1 FROM api_keys WHERE user_id = ? AND is_active = 1 LIMIT 1",
            (user["id"],),
        )
        return row is not None
    org_id = user.get("organization_id")
    if not org_id:
        return False
    row = fetch_one(
        "SELECT 1 FROM api_keys WHERE organization_id = ? AND is_active = 1 LIMIT 1",
        (org_id,),
    )
    return row is not None


def has_welcomed(user: dict[str, Any]) -> bool:
    """Whether this developer has already seen the first-login welcome.

    Company accounts have no welcome flow, so they are always considered welcomed.
    """
    if user.get("user_type") != "developer":
        return True
    row = fetch_one("SELECT welcomed_at FROM developer_profiles WHERE user_id = ?", (user["id"],))
    return bool(row and row["welcomed_at"])


def mark_welcomed(
    user_id: str,
    acquisition_source: str | None = None,
    acquisition_prompt: str | None = None,
) -> None:
    """Record that a developer has seen the welcome intro (idempotent — set once).

    The optional "How did you find Kodwai?" answer is stored when given; a later answer replaces
    an earlier one. Company accounts have no developer profile, so nothing is written for them.
    """
    execute(
        "UPDATE developer_profiles SET welcomed_at = datetime('now'), updated_at = datetime('now') "
        "WHERE user_id = ? AND welcomed_at IS NULL",
        (user_id,),
    )
    if acquisition_source:
        execute(
            "UPDATE developer_profiles SET acquisition_source = ?, acquisition_prompt = ?, updated_at = datetime('now') "
            "WHERE user_id = ?",
            (acquisition_source, acquisition_prompt or None, user_id),
        )


VERIFY_RESEND_WINDOW_MINUTES = 10


def _send_verification(user_id: str, email: str, name: str | None, token: str, client_url: str, dedupe_key: str) -> None:
    """Email the verification link through the tracked transactional path (non-blocking).

    Same sender and link as before (EMAIL_FROM_TRANSACTIONAL, {client_url}/verify?token=...); the
    email_sends row is what rate-limits resend-verification.
    """
    rendered = email_templates.verify_email(name=name, verify_url=f"{client_url}/verify?token={token}")
    send_tracked_in_background(
        user_id, email, "verify_email", rendered.subject, rendered.html, rendered.text, "transactional", dedupe_key,
    )


def resend_verification(email: str, client_url: str = "") -> None:
    """Re-send the verification link. Silent on unknown, verified or banned accounts.

    Rate limit: at most one verification email per address per 10 minutes, looked up in
    email_sends; the 10-minute bucket in the dedupe key also stops two concurrent requests.
    """
    user = fetch_one(
        "SELECT id, email, name, email_verified, email_verification_token, is_banned FROM users WHERE email = ?",
        (email,),
    )
    if user is None or user["email_verified"] or user["is_banned"]:
        return
    recent = fetch_one(
        """SELECT 1 FROM email_sends
           WHERE (user_id = ? OR lower(to_email) = lower(?))
             AND template IN ('verify_email', 'verify_reminder') AND status IN ('sent', 'claimed')
             AND julianday(created_at) > julianday('now', ?)
           LIMIT 1""",
        (user["id"], user["email"], f"-{VERIFY_RESEND_WINDOW_MINUTES} minutes"),
    )
    if recent:
        return
    token = user["email_verification_token"]
    if not token:
        token = secrets.token_hex(32)
        execute("UPDATE users SET email_verification_token = ? WHERE id = ?", (token, user["id"]))
    bucket = int(time.time() // (VERIFY_RESEND_WINDOW_MINUTES * 60))
    _send_verification(user["id"], user["email"], user["name"], token, client_url, f"verify_email:{user['id']}:{bucket}")


def signup(
    email: str,
    password: str,
    name: str,
    user_type: str = "company",
    organization_name: str | None = None,
    client_url: str = "",
    marketing_consent: bool = False,
) -> dict[str, Any]:
    """Register a new user. Company users get an organization; developer users do not.

    marketing_consent comes from the unchecked "product news" box at signup and sets
    users.marketing_consent_at. Onboarding email does not depend on it.
    """
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
        # Developer signup — no org. Username is auto-generated from the email.
        username = _generate_unique_username(email)
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

    if marketing_consent:
        execute("UPDATE users SET marketing_consent_at = datetime('now') WHERE id = ?", (user_id,))

    # Send verification email
    _send_verification(user_id, email, name, email_verification_token, client_url, f"verify_email:{user_id}:signup")
    capture(user_id, "signup_completed", {"method": "email", "user_type": user_type})

    return {
        "message": "Account created. Please check your email to verify your account.",
        # Lets the web app identify the new account in analytics with the same id the API uses.
        "user": {"id": user_id, "user_type": user_type},
    }


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

    # GitHub-only accounts have an empty password_hash, which bcrypt rejects with an error (500).
    if not user["password_hash"] or not verify_password(password, user["password_hash"]):
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


PASSWORD_RESET_TOKEN_TTL = timedelta(hours=1)


def request_password_reset(email: str, client_url: str = "") -> None:
    """Issue a password reset token and email the link. Silent on missing accounts."""
    user = fetch_one("SELECT id FROM users WHERE email = ?", (email,))
    if user is None:
        return  # Don't reveal whether the email exists

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + PASSWORD_RESET_TOKEN_TTL).isoformat()
    execute(
        "INSERT INTO password_reset_tokens (id, user_id, token, expires_at) VALUES (?, ?, ?, ?)",
        (secrets.token_hex(16), user["id"], token, expires_at),
    )
    send_password_reset_email(email, token, client_url)


def reset_password(token: str, new_password: str) -> None:
    """Consume a reset token and update the user's password."""
    row = fetch_one(
        "SELECT id, user_id, expires_at, used_at FROM password_reset_tokens WHERE token = ?",
        (token,),
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link is invalid. Request a new one.",
        )
    if row["used_at"] is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link has already been used. Request a new one.",
        )
    if datetime.now(timezone.utc) > datetime.fromisoformat(row["expires_at"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This reset link has expired. Request a new one.",
        )

    password_hash = hash_password(new_password)
    execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, row["user_id"]))
    execute(
        "UPDATE password_reset_tokens SET used_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), row["id"]),
    )


CLI_AUTH_CODE_TTL = timedelta(minutes=10)


def create_cli_auth_code(user_id: str) -> dict[str, Any]:
    """Mint a short-lived, single-use authorization code for the CLI loopback flow.

    Called by an authenticated web session. The CLI later exchanges this code for
    an access token via `exchange_cli_auth_code`.
    """
    code = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + CLI_AUTH_CODE_TTL).isoformat()
    execute(
        "INSERT INTO cli_auth_codes (id, user_id, code, expires_at) VALUES (?, ?, ?, ?)",
        (secrets.token_hex(16), user_id, code, expires_at),
    )
    return {"code": code, "expires_in": int(CLI_AUTH_CODE_TTL.total_seconds())}


def exchange_cli_auth_code(code: str) -> dict[str, Any]:
    """Consume a CLI authorization code and return an access token + user.

    Validates the code is real, unused, and unexpired, then marks it used.
    """
    row = fetch_one(
        "SELECT id, user_id, expires_at, used_at FROM cli_auth_codes WHERE code = ?",
        (code,),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid authorization code.")
    if row["used_at"] is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This authorization code has already been used.")
    if datetime.now(timezone.utc) > datetime.fromisoformat(row["expires_at"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This authorization code has expired.")

    execute(
        "UPDATE cli_auth_codes SET used_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), row["id"]),
    )

    user = fetch_one(
        "SELECT id, email, name, role, organization_id, user_type, username, email_verified, is_banned, banned_reason, created_at FROM users WHERE id = ?",
        (row["user_id"],),
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.get("is_banned"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Account banned: {user.get('banned_reason', 'Account suspended')}")

    access_token = create_access_token({"sub": user["id"]})
    user_response = {k: v for k, v in user.items() if k not in ("is_banned", "banned_reason")}
    user_response["has_claude_api_key"] = has_claude_api_key(user_response)
    capture(user["id"], "cli_login")
    return {"access_token": access_token, "user": user_response}


_USERNAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def update_password(user_id: str, current_password: str, new_password: str) -> None:
    """Verify the user's current password and replace it with a new one."""
    row = fetch_one("SELECT password_hash FROM users WHERE id = ?", (user_id,))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    stored_hash = row["password_hash"] or ""
    if not stored_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account doesn't have a password yet. Use 'Forgot password' to set one.",
        )
    if not verify_password(current_password, stored_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )
    if current_password == new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current one.",
        )

    execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user_id))


def update_username(user_id: str, new_username: str) -> dict[str, Any]:
    """Update the authenticated user's username after validation + uniqueness check."""
    candidate = new_username.strip().lower()
    if not _USERNAME_PATTERN.match(candidate):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username can only contain lowercase letters, numbers, hyphens, and underscores.",
        )
    if not (3 <= len(candidate) <= 50):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be between 3 and 50 characters.",
        )

    existing = fetch_one(
        "SELECT id FROM users WHERE username = ? AND id != ?",
        (candidate, user_id),
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That username is already taken.",
        )

    execute("UPDATE users SET username = ? WHERE id = ?", (candidate, user_id))

    user = fetch_one(
        "SELECT id, email, name, role, organization_id, user_type, username, email_verified, created_at FROM users WHERE id = ?",
        (user_id,),
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user["has_claude_api_key"] = has_claude_api_key(user)
    return user


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
    # The token is single-use, so this runs once per account. No-op while lifecycle_emails is off.
    from app.services import lifecycle
    lifecycle.trigger_welcome(user["id"])

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
        user_response["has_claude_api_key"] = has_claude_api_key(user_response)
        return {"access_token": access_token, "user": user_response, "is_new_user": False}

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
        user_response["has_claude_api_key"] = has_claude_api_key(user_response)
        return {"access_token": access_token, "user": user_response, "is_new_user": False}

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
    capture(user_id, "signup_completed", {"method": "github", "user_type": "developer"})
    # GitHub accounts arrive verified, so the welcome goes now. No-op while lifecycle_emails is off.
    from app.services import lifecycle
    lifecycle.trigger_welcome(user_id)

    user = fetch_one(
        "SELECT id, email, name, role, organization_id, user_type, username, email_verified, created_at FROM users WHERE id = ?",
        (user_id,),
    )
    if user is not None:
        user["has_claude_api_key"] = False
    access_token = create_access_token({"sub": user_id})
    return {"access_token": access_token, "user": user, "is_new_user": True}
