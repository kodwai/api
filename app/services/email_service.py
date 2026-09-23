from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import threading
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import resend

from app.core.config import settings
from app.core.database import execute, execute_returning, fetch_one
from app.services.analytics_events import capture
from app.services.feature_flags import flag_active_by_key

logger = logging.getLogger(__name__)


def _configure_resend() -> None:
    """Set the Resend API key."""
    resend.api_key = settings.RESEND_API_KEY


def _send_in_background(fn, *args, **kwargs) -> None:
    """Run an email send function in a background thread so it doesn't block the API."""
    def _run():
        try:
            fn(*args, **kwargs)
        except Exception:
            pass  # Already logged inside the send functions
    threading.Thread(target=_run, daemon=True).start()


def send_verification_email(to: str, token: str, base_url: str) -> None:
    """Send an email verification link (non-blocking)."""
    _send_in_background(_send_verification_email, to, token, base_url)


def _send_account_email(to: str, rendered: Any, log_label: str) -> None:
    """Untracked transactional send of an email_templates.RenderedEmail."""
    _configure_resend()
    try:
        resend.Emails.send(
            {
                "from": settings.EMAIL_FROM_TRANSACTIONAL,
                "to": [to],
                "subject": rendered.subject,
                "html": rendered.html,
                "text": rendered.text,
            }
        )
        logger.info("%s email sent to %s", log_label, to)
    except Exception:
        logger.exception("Failed to send %s email to %s", log_label, to)


def _send_verification_email(to: str, token: str, base_url: str) -> None:
    from app.services import email_templates  # local: email_templates imports this module

    rendered = email_templates.verify_email(name=None, verify_url=f"{base_url}/verify?token={token}")
    _send_account_email(to, rendered, "Verification")


def send_password_reset_email(to: str, token: str, base_url: str) -> None:
    """Send a password reset link (non-blocking)."""
    _send_in_background(_send_password_reset_email, to, token, base_url)


def _send_password_reset_email(to: str, token: str, base_url: str) -> None:
    from app.services import email_templates

    rendered = email_templates.password_reset(reset_url=f"{base_url}/reset-password?token={token}")
    _send_account_email(to, rendered, "Password reset")


def send_invitation_email(to: str, org_name: str, inviter_name: str, invitation_id: str, base_url: str) -> None:
    """Send a team invitation email (non-blocking)."""
    _send_in_background(_send_invitation_email, to, org_name, inviter_name, invitation_id, base_url)


def _send_invitation_email(
    to: str,
    org_name: str,
    inviter_name: str,
    invitation_id: str,
    base_url: str,
) -> None:
    """
        inviter_name: Name of the person who sent the invite.
        invitation_id: The invitation ID for the accept link.
        base_url: The client application base URL.
    """
    from app.services import email_templates

    rendered = email_templates.org_invitation(
        org_name=org_name,
        inviter_name=inviter_name,
        accept_url=f"{base_url}/invitations/{invitation_id}/accept",
    )
    _send_account_email(to, rendered, f"Invitation ({org_name})")


def send_session_invitation_email(to: str, candidate_name: str, project_title: str, session_id: str, session_token: str, time_limit: int, base_url: str) -> None:
    """Send a session invitation email (non-blocking)."""
    _send_in_background(_send_session_invitation_email, to, candidate_name, project_title, session_id, session_token, time_limit, base_url)


def _send_session_invitation_email(
    to: str,
    candidate_name: str,
    project_title: str,
    session_id: str,
    session_token: str,
    time_limit: int,
    base_url: str,
) -> None:
    """
        candidate_name: Name of the candidate.
        project_title: Title of the project/assessment.
        session_id: The session ID for the CLI start command.
        time_limit: Time limit in minutes.
        base_url: The application base URL.
    """
    from app.services import email_templates

    rendered = email_templates.session_invitation(
        candidate_name=candidate_name,
        project_title=project_title,
        session_id=session_id,
        session_token=session_token,
        time_limit=time_limit,
    )
    _send_account_email(to, rendered, f"Session invitation ({session_id})")


# ---------------------------------------------------------------------------
# Tracked sends (lifecycle, feedback, and transactional mail that needs a ledger)
# ---------------------------------------------------------------------------

STREAMS: tuple[str, ...] = ("transactional", "lifecycle", "feedback")
# Streams that carry List-Unsubscribe headers and honor unsubscribe/suppression.
UNSUBSCRIBABLE_STREAMS: tuple[str, ...] = ("lifecycle", "feedback")
# One-to-one replies the user asked for by writing in; only suppression (bounce, complaint) stops them.
UNSUBSCRIBE_EXEMPT_TEMPLATES: tuple[str, ...] = ("feedback_reply",)
# A failed row is retried (same dedupe and idempotency key) until it has this many attempts.
MAX_SEND_ATTEMPTS = 3


def unsubscribe_token(user_id: str) -> str:
    """Stateless unsubscribe token: HMAC-SHA256(UNSUBSCRIBE_SECRET, user_id), first 32 hex chars.

    Raises RuntimeError when UNSUBSCRIBE_SECRET is not configured.
    """
    if not settings.UNSUBSCRIBE_SECRET:
        raise RuntimeError("UNSUBSCRIBE_SECRET is not configured")
    digest = hmac.new(settings.UNSUBSCRIBE_SECRET.encode("utf-8"), user_id.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:32]


def verify_unsubscribe_token(user_id: str, token: str) -> bool:
    """Constant-time check of an unsubscribe token. False when the secret or either input is empty."""
    if not settings.UNSUBSCRIBE_SECRET or not user_id or not token:
        return False
    return hmac.compare_digest(unsubscribe_token(user_id), token)


def unsubscribe_url(user_id: str) -> str:
    """One-click unsubscribe URL for List-Unsubscribe and email footers."""
    query = urlencode({"u": user_id, "t": unsubscribe_token(user_id)})
    return f"{settings.PUBLIC_API_URL.rstrip('/')}/api/email/unsubscribe?{query}"


def with_utm(url: str, campaign: str, medium: str = "lifecycle", source: str = "email") -> str:
    """Append utm_source/utm_medium/utm_campaign to a link, keeping any existing query params."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("utm_")]
    query += [("utm_source", source), ("utm_medium", medium), ("utm_campaign", campaign)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def mask_email(email: str | None) -> str:
    """'jane@example.com' -> 'j***@example.com', for API responses and logs."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.rsplit("@", 1)
    return f"{local[:1]}***@{domain}"


def _gating_flag(stream: str, template: str) -> str | None:
    """Kill-switch flag that must be on before a real send. Defense in depth: callers check the
    same flags, but nothing reaches Resend while one is off. feedback_ack* templates (the instant
    acknowledgment and its founder notification) use feedback_ack_emails; every lifecycle send
    (welcome, milestones, drip) uses lifecycle_emails. Feedback replies are founder-initiated."""
    if template.startswith("feedback_ack"):
        return "feedback_ack_emails"
    if stream == "lifecycle":
        return "lifecycle_emails"
    return None


def _real_send_refusal(stream: str, template: str, user_id: str | None, reply_to: str | None) -> str | None:
    """Why a real (non-dry-run) send must not happen, or None when it may."""
    flag = _gating_flag(stream, template)
    if flag and not flag_active_by_key(flag):
        return f"flag_off:{flag}"
    if not settings.RESEND_API_KEY:
        return "resend_not_configured"
    if stream in UNSUBSCRIBABLE_STREAMS:
        if not settings.EMAIL_FROM_LIFECYCLE:
            return "email_from_lifecycle_unset"
        if not (reply_to or settings.EMAIL_REPLY_TO):
            return "reply_to_unset"
        if user_id and not settings.UNSUBSCRIBE_SECRET:
            return "unsubscribe_secret_unset"
    return None


def _result(
    status: str,
    *,
    email_send_id: str | None = None,
    provider_id: str | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {"status": status, "email_send_id": email_send_id, "provider_id": provider_id, "reason": reason, "error": error}


def _tag_value(value: str) -> str:
    # Resend tag values allow only ASCII letters, numbers, underscores and dashes.
    return re.sub(r"[^A-Za-z0-9_-]", "_", value)[:256]


def _idempotency_key(dedupe_key: str) -> str:
    # Resend caps idempotency keys at 256 characters; it keeps them for 24 hours, and the
    # UNIQUE dedupe_key in email_sends covers everything after that.
    return dedupe_key if len(dedupe_key) <= 256 else hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()


def _existing_send(dedupe_key: str) -> dict[str, Any] | None:
    return fetch_one("SELECT id, status, attempts FROM email_sends WHERE dedupe_key = ?", (dedupe_key,))


def send_tracked(
    user_id: str | None,
    to: str,
    template: str,
    subject: str,
    html: str,
    text: str,
    stream: str,
    dedupe_key: str,
    run_id: str | None = None,
    dry_run: bool = False,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send one email at most once per ``dedupe_key`` and record it in ``email_sends``. Synchronous.

    Claim-then-send: a row is claimed with ``INSERT ... ON CONFLICT DO NOTHING RETURNING`` before
    Resend is called, so concurrent or repeated calls with the same key send nothing. A failed row
    is re-claimed (same Resend idempotency key) until MAX_SEND_ATTEMPTS. A row left 'claimed' by a
    crash is never retried: missing one email beats sending it twice.

    lifecycle/feedback streams: sent from EMAIL_FROM_LIFECYCLE, reply-to EMAIL_REPLY_TO unless
    ``reply_to`` is given, List-Unsubscribe + List-Unsubscribe-Post headers when ``user_id`` is set,
    and skipped for unsubscribed or suppressed users (feedback_reply honors suppression only).
    transactional: EMAIL_FROM_TRANSACTIONAL.

    Returns ``{"status", "email_send_id", "provider_id", "reason", "error"}`` where status is:
      sent       Resend accepted it
      failed     Resend (or the claim) raised; ``error`` says why
      duplicate  the dedupe_key was already sent/claimed (``reason`` holds the existing status)
      skipped    not sent and nothing recorded; ``reason`` is unsubscribed, suppressed,
                 flag_off:<flag>, resend_not_configured, reply_to_unset, email_from_lifecycle_unset
                 or unsubscribe_secret_unset
      dry_run    would send (nothing written, the key is not consumed)
    Dry runs ignore flags and config (so a plan can be previewed before DNS setup) but do report
    unsubscribed, suppressed and duplicate. Raises ValueError only on bad arguments.
    """
    if stream not in STREAMS:
        raise ValueError(f"Unknown email stream: {stream}")
    if not to or not template or not dedupe_key:
        raise ValueError("to, template and dedupe_key are required")

    unsubscribable = stream in UNSUBSCRIBABLE_STREAMS
    if unsubscribable and user_id:
        state = fetch_one("SELECT email_unsubscribed_at, email_suppressed_at FROM users WHERE id = ?", (user_id,))
        if state and state["email_suppressed_at"]:
            return _result("skipped", reason="suppressed")
        # A founder reply answers a message the user sent, so it ignores the lifecycle
        # unsubscribe (suppression above still applies).
        if state and state["email_unsubscribed_at"] and template not in UNSUBSCRIBE_EXEMPT_TEMPLATES:
            return _result("skipped", reason="unsubscribed")

    if dry_run:
        existing = _existing_send(dedupe_key)
        if existing and not (existing["status"] == "failed" and existing["attempts"] < MAX_SEND_ATTEMPTS):
            return _result("duplicate", email_send_id=existing["id"], reason=existing["status"])
        return _result("dry_run", email_send_id=existing["id"] if existing else None)

    refusal = _real_send_refusal(stream, template, user_id, reply_to)
    if refusal:
        return _result("skipped", reason=refusal)

    try:
        claimed = execute_returning(
            """INSERT INTO email_sends (user_id, to_email, template, stream, dedupe_key, status, run_id, meta)
               VALUES (?, ?, ?, ?, ?, 'claimed', ?, ?)
               ON CONFLICT(dedupe_key) DO UPDATE SET
                   status = 'claimed', attempts = email_sends.attempts + 1, error = NULL,
                   to_email = excluded.to_email, run_id = excluded.run_id
               WHERE email_sends.status = 'failed' AND email_sends.attempts < ?
               RETURNING id""",
            (user_id, to, template, stream, dedupe_key, run_id, json.dumps(meta) if meta else None, MAX_SEND_ATTEMPTS),
        )
    except Exception as e:
        logger.exception("Could not claim email send %s (%s)", dedupe_key, template)
        return _result("failed", error=f"claim failed: {str(e)[:300]}")
    if not claimed:
        existing = _existing_send(dedupe_key)
        return _result("duplicate", email_send_id=existing["id"] if existing else None,
                       reason=existing["status"] if existing else None)
    send_id = claimed[0]["id"]

    all_headers = dict(headers or {})
    if unsubscribable and user_id:
        all_headers["List-Unsubscribe"] = f"<{unsubscribe_url(user_id)}>"
        all_headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    effective_reply_to = reply_to or (settings.EMAIL_REPLY_TO if unsubscribable else None)
    params: dict[str, Any] = {
        "from": settings.EMAIL_FROM_LIFECYCLE if unsubscribable else settings.EMAIL_FROM_TRANSACTIONAL,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
        "tags": [{"name": "template", "value": _tag_value(template)}, {"name": "stream", "value": stream}],
    }
    if effective_reply_to:
        params["reply_to"] = effective_reply_to
    if all_headers:
        params["headers"] = all_headers

    try:
        _configure_resend()
        response = resend.Emails.send(params, {"idempotency_key": _idempotency_key(dedupe_key)})  # type: ignore[arg-type]
        provider_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
    except Exception as e:
        error = str(e)[:500]
        logger.exception("Tracked email %s (%s) failed", send_id, template)
        try:
            execute("UPDATE email_sends SET status = 'failed', error = ? WHERE id = ?", (error, send_id))
        except Exception:
            logger.exception("Could not mark email send %s failed", send_id)
        return _result("failed", email_send_id=send_id, error=error)

    try:
        execute(
            "UPDATE email_sends SET status = 'sent', provider_id = ?, sent_at = datetime('now'), error = NULL WHERE id = ?",
            (provider_id, send_id),
        )
    except Exception:
        # The email went out; the row stays 'claimed', which blocks a resend. Log and move on.
        logger.exception("Email send %s went out but its row could not be updated", send_id)
    capture(user_id, "email_sent", {"template": template, "stream": stream, "email_send_id": send_id})
    logger.info("Tracked email %s (%s) sent", send_id, template)
    return _result("sent", email_send_id=send_id, provider_id=provider_id)


def send_tracked_in_background(*args: Any, **kwargs: Any) -> None:
    """Fire-and-forget ``send_tracked`` for request paths (welcome on verify, first score)."""
    _send_in_background(send_tracked, *args, **kwargs)
