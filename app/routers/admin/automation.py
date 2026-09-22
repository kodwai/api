"""Automation identity and token management.

``whoami`` accepts any automation token or superadmin JWT. Token CRUD is superadmin-JWT only:
an automation token can never mint, list or revoke tokens.
"""
from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, HTTPException, status

from app.core.admin_deps import AdminUser
from app.core.automation_deps import AutomationPrincipal
from app.core.database import execute, fetch_one
from app.schemas.automation import AutomationTokenCreate
from app.services import automation_tokens

router = APIRouter(tags=["admin-automation"])


def _audit(admin_id: str, action: str, entity_id: str, details: dict) -> None:
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, ?, 'automation_token', ?, ?)",
        (secrets.token_hex(16), admin_id, action, entity_id, json.dumps(details)),
    )


@router.get("/automation/whoami")
def automation_whoami(principal: AutomationPrincipal) -> dict:
    return {
        "via": principal["via"],
        "token_id": principal["token_id"],
        "scopes": principal["scopes"],
        "owner_user_id": principal["id"],
    }


@router.post("/automation-tokens", status_code=status.HTTP_201_CREATED)
def create_automation_token(body: AutomationTokenCreate, current_admin: AdminUser) -> dict:
    """Mint a token. The plaintext is in this response only; store it in the Keychain."""
    try:
        row = automation_tokens.mint_token(body.name, body.scopes, current_admin["id"], body.expires_days)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    _audit(current_admin["id"], "create_automation_token", row["id"], {
        "name": row["name"], "scopes": row["scopes"], "token_prefix": row["token_prefix"], "expires_at": row["expires_at"],
    })
    return {
        "id": row["id"],
        "name": row["name"],
        "token": row["token"],
        "token_prefix": row["token_prefix"],
        "scopes": row["scopes"],
        "expires_at": row["expires_at"],
    }


@router.get("/automation-tokens")
def list_automation_tokens(current_admin: AdminUser) -> dict:
    return {"items": automation_tokens.list_tokens(), "allowed_scopes": list(automation_tokens.AUTOMATION_SCOPES)}


@router.delete("/automation-tokens/{token_id}")
def revoke_automation_token(token_id: str, current_admin: AdminUser) -> dict:
    """Revoke (idempotent). The row is kept so the audit trail and last_used_at survive."""
    existing = fetch_one("SELECT id, name, revoked_at FROM automation_tokens WHERE id = ?", (token_id,))
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    if not existing["revoked_at"]:
        execute("UPDATE automation_tokens SET revoked_at = datetime('now') WHERE id = ?", (token_id,))
        _audit(current_admin["id"], "revoke_automation_token", token_id, {"name": existing["name"]})
    return automation_tokens.get_token(token_id) or {}
