"""Lifecycle email runner and send ledger (mounted under /api/admin).

Routes:
  POST /lifecycle/run       scope lifecycle:run   plan (dry run, the default) or send one pass
  GET  /lifecycle/preview   scope lifecycle:run   render a template for a user (or a sample user)
  GET  /email-sends         scope email:read      the send ledger, masked recipients
"""
from __future__ import annotations

import json
import secrets
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.automation_deps import require_scope
from app.core.database import execute
from app.schemas.lifecycle import (
    EmailSendsResponse,
    LifecyclePreviewResponse,
    LifecycleRunRequest,
    LifecycleRunResponse,
)
from app.services import lifecycle

router = APIRouter(tags=["admin-lifecycle"])

LifecycleScope = Annotated[dict, Depends(require_scope("lifecycle:run"))]
EmailReadScope = Annotated[dict, Depends(require_scope("email:read"))]


def _parse_since(since: str | None) -> str | None:
    if since is None:
        return None
    try:
        return date.fromisoformat(since).isoformat()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="since must be YYYY-MM-DD") from e


@router.post("/lifecycle/run", response_model=LifecycleRunResponse)
def run_lifecycle(body: LifecycleRunRequest, principal: LifecycleScope) -> dict:
    """Plan or send one pass. A real run (dry_run=false) is refused, with refused_reason and the
    plan marked 'refused', unless the lifecycle_emails flag is on and the sender config is set."""
    try:
        result = lifecycle.run(dry_run=body.dry_run, limit=body.limit, templates=body.templates, run_id=body.run_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    if not body.dry_run:
        # Real runs (sent or refused) are audited against the token's owner, a real superadmin.
        execute(
            "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) "
            "VALUES (?, ?, 'lifecycle_run', 'lifecycle', ?, ?)",
            (secrets.token_hex(16), principal["id"], result["run_id"], json.dumps({
                "via": principal.get("via"),
                "token_id": principal.get("token_id"),
                "refused_reason": result["refused_reason"],
                "counts": result["counts"],
                "limit": body.limit,
                "templates": body.templates,
            })),
        )
    return result


@router.get("/lifecycle/preview", response_model=LifecyclePreviewResponse)
def preview_lifecycle(
    principal: LifecycleScope,
    template: str = Query(..., min_length=1, max_length=64),
    user_id: str | None = Query(default=None, max_length=64),
) -> dict:
    """Render a template for a real user (any account) or, without user_id, a sample user."""
    try:
        return lifecycle.preview(template, user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/email-sends", response_model=EmailSendsResponse)
def list_email_sends(
    principal: EmailReadScope,
    since: str | None = Query(default=None, description="YYYY-MM-DD, UTC"),
    template: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    return {"items": lifecycle.list_email_sends(_parse_since(since), template, limit)}
