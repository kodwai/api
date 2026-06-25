from __future__ import annotations

import logging
import secrets

import httpx
from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.core.deps import CurrentUser
from app.schemas.api_key import ApiKeyCreate, ApiKeyResponse
from app.services.encryption_service import decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _validate_anthropic_key(api_key: str) -> bool:
    """Validate an Anthropic API key by making a lightweight test request.

    Returns True if the key is valid, False otherwise.
    """
    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "Hi"}],
            },
            timeout=15.0,
        )
        # 200 means the key works; 401 means invalid key
        # Other errors (rate limit, etc.) mean the key is likely valid
        if response.status_code == 401:
            return False
        return True
    except httpx.RequestError:
        logger.exception("Failed to validate Anthropic API key")
        # Network error — don't block the user, assume valid
        return True


def _is_developer(user: dict) -> bool:
    return user.get("user_type") == "developer"


@router.get("", response_model=list[ApiKeyResponse])
def list_api_keys(current_user: CurrentUser) -> list[ApiKeyResponse]:
    """List API keys scoped to org (company) or user (developer)."""
    if _is_developer(current_user):
        rows = fetch_all(
            """SELECT id, label, key_last4, is_active, created_at
               FROM api_keys WHERE user_id = ? ORDER BY created_at DESC""",
            (current_user["id"],),
        )
    else:
        rows = fetch_all(
            """SELECT id, label, key_last4, is_active, created_at
               FROM api_keys WHERE organization_id = ? ORDER BY created_at DESC""",
            (current_user["organization_id"],),
        )
    return [ApiKeyResponse(**row) for row in rows]


@router.post("", response_model=ApiKeyResponse, status_code=201)
def create_api_key(body: ApiKeyCreate, current_user: CurrentUser) -> ApiKeyResponse:
    """Add a new Anthropic API key. Validates the key before storing."""
    if not _validate_anthropic_key(body.key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Anthropic API key. Please check the key and try again.",
        )

    encrypted, iv = encrypt_api_key(body.key, settings.ENCRYPTION_KEY)
    key_last4 = body.key[-4:]
    key_id = secrets.token_hex(16)

    if _is_developer(current_user):
        execute(
            """INSERT INTO api_keys (id, user_id, encrypted_key, key_iv, key_last4, label, is_active)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (key_id, current_user["id"], encrypted, iv, key_last4, body.label),
        )
    else:
        execute(
            """INSERT INTO api_keys (id, organization_id, encrypted_key, key_iv, key_last4, label, is_active)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (key_id, current_user["organization_id"], encrypted, iv, key_last4, body.label),
        )

    row = fetch_one(
        "SELECT id, label, key_last4, is_active, created_at FROM api_keys WHERE id = ?",
        (key_id,),
    )
    return ApiKeyResponse(**row)  # type: ignore[arg-type]


@router.delete("/{key_id}", status_code=204)
def delete_api_key(key_id: str, current_user: CurrentUser):
    """Delete an API key."""
    if _is_developer(current_user):
        existing = fetch_one(
            "SELECT id FROM api_keys WHERE id = ? AND user_id = ?",
            (key_id, current_user["id"]),
        )
    else:
        existing = fetch_one(
            "SELECT id FROM api_keys WHERE id = ? AND organization_id = ?",
            (key_id, current_user["organization_id"]),
        )
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")

    execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    return None
