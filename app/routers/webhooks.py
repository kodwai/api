"""Inbound provider webhooks (mounted under /api).

Routes:
  POST /webhooks/resend   svix-signed; verified over the raw body with RESEND_WEBHOOK_SECRET

Resend events (https://resend.com/docs/webhooks/event-types) map onto email_sends (matched by
provider_id = data.email_id) and the recipient's suppression state:
  email.bounced     row failed for good; a Permanent bounce also suppresses the user
  email.complained  suppresses the user (spam report); the row stays 'sent' with the note
  email.suppressed  Resend refused an address on its suppression list: row failed, user suppressed
  email.failed      row failed but still retryable (reasons like reached_daily_quota are ours,
                    not the recipient's), so it never suppresses the user
  email.delivered   stamps meta.delivered_at on the row
Suppression stops lifecycle and feedback mail (send_tracked and the runner's base filter); account
mail still goes out. Handlers are idempotent, so svix retries are harmless.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import resend
from fastapi import APIRouter, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import execute, fetch_one
from app.services.email_service import MAX_SEND_ATTEMPTS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


def _suppress(user_id: str | None, email: str | None, reason: str) -> bool:
    """Set email_suppressed_at (first time only) and the latest reason. True when a user matched."""
    if user_id:
        target = fetch_one("SELECT id FROM users WHERE id = ?", (user_id,))
    elif email:
        target = fetch_one("SELECT id FROM users WHERE lower(email) = lower(?)", (email,))
    else:
        target = None
    if target is None:
        return False
    execute(
        "UPDATE users SET email_suppressed_at = COALESCE(email_suppressed_at, datetime('now')), "
        "email_suppressed_reason = ? WHERE id = ?",
        (reason[:200], target["id"]),
    )
    return True


def _fail_row(row: dict[str, Any] | None, error: str, *, final: bool) -> None:
    """Mark a ledger row failed. final=True also exhausts its attempts so it is never retried."""
    if row is None:
        return
    if final:
        execute(
            "UPDATE email_sends SET status = 'failed', error = ?, attempts = MAX(attempts, ?) WHERE id = ?",
            (error[:500], MAX_SEND_ATTEMPTS, row["id"]),
        )
    else:
        execute("UPDATE email_sends SET status = 'failed', error = ? WHERE id = ?", (error[:500], row["id"]))


def apply_resend_event(event: dict[str, Any]) -> dict[str, Any]:
    """Apply one verified Resend event. Returns what was done (for logs and tests)."""
    event_type = str(event.get("type") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    email_id = data.get("email_id")
    recipients = data.get("to") if isinstance(data.get("to"), list) else []

    row = fetch_one(
        "SELECT id, user_id, to_email, status FROM email_sends WHERE provider_id = ?", (email_id,),
    ) if email_id else None
    user_id = row["user_id"] if row else None
    recipient = row["to_email"] if row else (recipients[0] if recipients else None)
    outcome: dict[str, Any] = {"type": event_type, "email_send_id": row["id"] if row else None, "suppressed": False}

    if event_type == "email.delivered":
        if row is not None:
            execute(
                "UPDATE email_sends SET meta = json_set(COALESCE(meta, '{}'), '$.delivered_at', ?) WHERE id = ?",
                (str(event.get("created_at") or data.get("created_at") or ""), row["id"]),
            )
    elif event_type == "email.bounced":
        bounce = data.get("bounce") if isinstance(data.get("bounce"), dict) else {}
        kind = str(bounce.get("type") or "Permanent")
        detail = str(bounce.get("subType") or kind)
        _fail_row(row, f"bounced ({kind}/{detail}): {str(bounce.get('message') or '')[:300]}", final=True)
        if kind.lower() == "permanent":
            outcome["suppressed"] = _suppress(user_id, recipient, f"bounced:{detail}")
    elif event_type == "email.complained":
        if row is not None:
            execute("UPDATE email_sends SET error = 'complained' WHERE id = ?", (row["id"],))
        outcome["suppressed"] = _suppress(user_id, recipient, "complained")
    elif event_type == "email.suppressed":
        suppressed = data.get("suppressed") if isinstance(data.get("suppressed"), dict) else {}
        detail = str(suppressed.get("type") or "suppressed")
        _fail_row(row, f"suppressed by Resend: {detail}", final=True)
        outcome["suppressed"] = _suppress(user_id, recipient, f"suppressed:{detail}")
    elif event_type == "email.failed":
        failed = data.get("failed") if isinstance(data.get("failed"), dict) else {}
        _fail_row(row, f"failed: {str(failed.get('reason') or 'unknown')[:300]}", final=False)
    else:
        outcome["ignored"] = True
    return outcome


@router.post("/webhooks/resend")
async def resend_webhook(request: Request) -> dict:
    secret = settings.RESEND_WEBHOOK_SECRET
    if not secret:
        # Never accept unsigned events: refuse until the secret is configured.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook not configured")

    raw = await request.body()
    payload = raw.decode("utf-8", errors="replace")
    headers = {
        "id": request.headers.get("svix-id", ""),
        "timestamp": request.headers.get("svix-timestamp", ""),
        "signature": request.headers.get("svix-signature", ""),
    }
    try:
        resend.Webhooks.verify({"payload": payload, "headers": headers, "webhook_secret": secret})  # type: ignore[typeddict-item]
    except ValueError as e:
        logger.warning("Rejected Resend webhook: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature") from e

    try:
        event = json.loads(payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON") from e
    if not isinstance(event, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid event")

    outcome = await run_in_threadpool(apply_resend_event, event)
    logger.info("Resend webhook %s applied: %s", outcome.get("type"), outcome)
    return {"ok": True, **outcome}
