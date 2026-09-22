"""Scoped auth for admin endpoints the daily growth routine calls.

A request authenticates with ``Authorization: Bearer <token>`` where the token is either:
  - an automation token (``kdw_at_...``), which carries only the scopes it was minted with, or
  - a superadmin admin JWT (the admin UI's token), which carries every scope.

The principal returned has ``id`` = a real superadmin user id (the token's owner), so
``admin_audit_log.admin_user_id`` keeps working unchanged for routes that opt in.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.admin_deps import get_current_admin
from app.core.database import execute, fetch_one
from app.services.automation_tokens import AUTOMATION_SCOPES, TOKEN_PREFIX, hash_token, parse_scopes

automation_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _parse_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized.replace(" ", "T", 1))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _from_automation_token(raw: str) -> dict[str, Any]:
    digest = hash_token(raw)
    row = fetch_one(
        "SELECT id, token_hash, scopes, owner_user_id, expires_at, revoked_at FROM automation_tokens WHERE token_hash = ?",
        (digest,),
    )
    if row is None or not hmac.compare_digest(row["token_hash"], digest):
        raise _unauthorized("Invalid automation token")
    if row["revoked_at"]:
        raise _unauthorized("Automation token revoked")
    if row["expires_at"] and _parse_utc(row["expires_at"]) <= datetime.now(timezone.utc):
        raise _unauthorized("Automation token expired")

    # A token is only as strong as its owner: it dies with the owner's superadmin status.
    owner = fetch_one("SELECT id, is_superadmin, is_banned FROM users WHERE id = ?", (row["owner_user_id"],))
    if owner is None or not owner["is_superadmin"] or owner["is_banned"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token owner is no longer a superadmin")

    return {"id": owner["id"], "via": "token", "token_id": row["id"], "scopes": parse_scopes(row["scopes"])}


def get_automation_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(automation_bearer)],
) -> dict[str, Any]:
    """Authenticate an automation token or a superadmin JWT. No scope check.

    Returns ``{"id": owner_user_id, "via": "token"|"superadmin", "token_id", "scopes"}``.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Not authenticated")
    raw = credentials.credentials
    if raw.startswith(TOKEN_PREFIX):
        principal = _from_automation_token(raw)
        execute("UPDATE automation_tokens SET last_used_at = datetime('now') WHERE id = ?", (principal["token_id"],))
        return principal
    # Anything else must be a superadmin admin JWT (401 on a developer/company JWT, 403 if not superadmin).
    admin = get_current_admin(credentials)
    return {"id": admin["id"], "via": "superadmin", "token_id": None, "scopes": list(AUTOMATION_SCOPES)}


def require_scope(scope: str):
    """FastAPI dependency factory: authenticate, then 403 unless the principal carries ``scope``.

    Usage: ``current: Annotated[dict, Depends(require_scope("lifecycle:run"))]``.
    """
    if scope not in AUTOMATION_SCOPES:
        # Fail at import time on a typo instead of silently locking the route.
        raise ValueError(f"Unknown automation scope: {scope}")

    def _dep(principal: Annotated[dict[str, Any], Depends(get_automation_principal)]) -> dict[str, Any]:
        if scope not in principal["scopes"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Missing scope: {scope}")
        return principal

    return _dep


AutomationPrincipal = Annotated[dict[str, Any], Depends(get_automation_principal)]
