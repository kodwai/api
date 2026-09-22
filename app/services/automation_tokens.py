"""Scoped automation tokens (kdw_at_...) for the daily growth routine.

Only the sha256 hash of a token is stored. The plaintext exists once, in the mint response,
and is then kept in the founder's macOS Keychain (service "kodwai-automation").
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.database import execute_returning, fetch_all, fetch_one

TOKEN_PREFIX = "kdw_at_"

# Every scope an automation token can carry. There is deliberately no scope for users,
# challenges or minting tokens: those stay behind a superadmin JWT.
AUTOMATION_SCOPES: tuple[str, ...] = (
    "lifecycle:run",
    "email:read",
    "feedback:read",
    "feedback:reply",
    "blog:write",
    "blog:publish",
    "stats:read",
)

DEFAULT_EXPIRES_DAYS = 90
MAX_EXPIRES_DAYS = 365


def hash_token(token: str) -> str:
    """sha256 hex digest of a plaintext token (the lookup key in automation_tokens)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_scopes(scopes: list[str]) -> list[str]:
    """De-duplicate and sort scopes. Raises ValueError naming any unknown scope."""
    cleaned = sorted({s.strip() for s in scopes if s and s.strip()})
    unknown = [s for s in cleaned if s not in AUTOMATION_SCOPES]
    if unknown:
        raise ValueError(f"Unknown scope(s): {', '.join(unknown)}. Allowed: {', '.join(AUTOMATION_SCOPES)}")
    if not cleaned:
        raise ValueError("At least one scope is required")
    return cleaned


def parse_scopes(raw: str | None) -> list[str]:
    """Decode the stored JSON scopes column; anything malformed decodes to no scopes."""
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [s for s in value if isinstance(s, str)] if isinstance(value, list) else []


def mint_token(name: str, scopes: list[str], owner_user_id: str, expires_days: int = DEFAULT_EXPIRES_DAYS) -> dict[str, Any]:
    """Create a token and return its row plus the plaintext ("token"), which is never stored.

    Raises ValueError on an unknown scope, an empty name or an out-of-range expiry.
    """
    name = name.strip()
    if not name:
        raise ValueError("Token name is required")
    if not 1 <= expires_days <= MAX_EXPIRES_DAYS:
        raise ValueError(f"expires_days must be between 1 and {MAX_EXPIRES_DAYS}")
    normalized = normalize_scopes(scopes)

    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(32)
    # Enough of the token to recognize it in a list, never enough to use it.
    token_prefix = plaintext[: len(TOKEN_PREFIX) + 6]
    expires_at = (datetime.now(timezone.utc) + timedelta(days=expires_days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = execute_returning(
        """INSERT INTO automation_tokens (name, token_hash, token_prefix, scopes, owner_user_id, expires_at)
           VALUES (?, ?, ?, ?, ?, ?)
           RETURNING id, name, token_prefix, scopes, owner_user_id, expires_at, created_at""",
        (name, hash_token(plaintext), token_prefix, json.dumps(normalized), owner_user_id, expires_at),
    )
    row = rows[0]
    row["scopes"] = normalized
    row["token"] = plaintext
    return row


def _public(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if k != "token_hash"}
    out["scopes"] = parse_scopes(row.get("scopes"))
    return out


def list_tokens() -> list[dict[str, Any]]:
    """All tokens, newest first, without hashes."""
    rows = fetch_all(
        """SELECT id, name, token_prefix, scopes, owner_user_id, expires_at, revoked_at, last_used_at, created_at
           FROM automation_tokens ORDER BY created_at DESC"""
    )
    return [_public(r) for r in rows]


def get_token(token_id: str) -> dict[str, Any] | None:
    row = fetch_one(
        """SELECT id, name, token_prefix, scopes, owner_user_id, expires_at, revoked_at, last_used_at, created_at
           FROM automation_tokens WHERE id = ?""",
        (token_id,),
    )
    return _public(row) if row else None
