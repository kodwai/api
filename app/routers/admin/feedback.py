from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.admin_deps import AdminUser
from app.core.automation_deps import require_scope
from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.schemas.feedback import AdminFeedbackUpdate
from app.schemas.feedback_reply import FeedbackReplyRequest
from app.services import feedback_emails
from app.services.email_service import send_tracked

router = APIRouter(tags=["admin-feedback"])

FeedbackReader = Annotated[dict[str, Any], Depends(require_scope("feedback:read"))]
FeedbackReplier = Annotated[dict[str, Any], Depends(require_scope("feedback:reply"))]

_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
# URL segment -> kind used in dedupe keys, inbox items and audit rows.
_KIND_TABLES = {"platform": "platform_feedback", "challenge": "challenge_feedback"}


def _valid_date(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        date.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="since must be YYYY-MM-DD") from e
    return value


def _audit(principal: dict[str, Any], action: str, entity_type: str, entity_id: str, details: dict) -> None:
    if principal.get("via") == "token":
        details = {**details, "via": "token", "token_id": principal.get("token_id")}
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (secrets.token_hex(16), principal["id"], action, entity_type, entity_id, json.dumps(details)),
    )


# ── Inbox (daily routine) ───────────────────────────────────────────


@router.get("/feedback/inbox")
def feedback_inbox(
    principal: FeedbackReader,
    unreplied: bool = False,
    since: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    limit: int = Query(200, ge=1, le=500),
) -> dict:
    """Platform and challenge feedback in one list, newest first.

    ``unreplied=true`` keeps items with no emailed reply and no admin response, drops dismissed
    platform feedback, and drops challenge ratings without a comment (nothing to reply to).
    ``since`` filters platform feedback by created_at and challenge feedback by updated_at, so an
    edited challenge comment shows up again. Challenge feedback has no status column: its
    ``status`` is derived ("resolved" once answered, otherwise "new").
    """
    since = _valid_date(since)

    pf_where = ["1=1"]
    pf_params: list[Any] = []
    cf_where = ["1=1"]
    cf_params: list[Any] = []
    if since:
        pf_where.append("pf.created_at >= ?")
        pf_params.append(since)
        cf_where.append("cf.updated_at >= ?")
        cf_params.append(since)
    if unreplied:
        pf_where.append(
            "pf.reply_emailed_at IS NULL AND (pf.admin_response IS NULL OR pf.admin_response = '') AND pf.status != 'dismissed'"
        )
        cf_where.append(
            "cf.reply_emailed_at IS NULL AND (cf.admin_response IS NULL OR cf.admin_response = '') "
            "AND cf.comment IS NOT NULL AND trim(cf.comment) != ''"
        )

    platform_rows = fetch_all(
        f"""SELECT pf.id, pf.user_id, u.name AS user_name, u.email AS user_email,
                   pf.category, pf.rating, pf.description AS message, pf.status, pf.page_url,
                   pf.is_flagged, pf.created_at, pf.updated_at, pf.admin_response, pf.admin_responded_at,
                   pf.reply_emailed_at
            FROM platform_feedback pf
            JOIN users u ON u.id = pf.user_id
            WHERE {' AND '.join(pf_where)}
            ORDER BY pf.created_at DESC LIMIT ?""",
        (*pf_params, limit),
    )
    challenge_rows = fetch_all(
        f"""SELECT cf.id, cf.user_id, u.name AS user_name, u.email AS user_email,
                   cf.challenge_id, c.title AS challenge_title, c.slug AS challenge_slug, cf.submission_id,
                   cf.rating_overall AS rating, cf.rating_difficulty, cf.rating_clarity, cf.comment AS message,
                   cf.created_at, cf.updated_at, cf.admin_response, cf.admin_responded_at, cf.reply_emailed_at
            FROM challenge_feedback cf
            JOIN users u ON u.id = cf.user_id
            JOIN challenges c ON c.id = cf.challenge_id
            WHERE {' AND '.join(cf_where)}
            ORDER BY cf.updated_at DESC LIMIT ?""",
        (*cf_params, limit),
    )

    items: list[dict[str, Any]] = []
    for r in platform_rows:
        items.append({
            "kind": "platform", "id": r["id"], "user_id": r["user_id"], "user_name": r["user_name"],
            "user_email": r["user_email"], "challenge_id": None, "challenge_title": None, "submission_id": None,
            "category": r["category"], "rating": r["rating"], "message": r["message"], "status": r["status"],
            "created_at": r["created_at"], "updated_at": r["updated_at"], "admin_response": r["admin_response"],
            "admin_responded_at": r["admin_responded_at"], "reply_emailed_at": r["reply_emailed_at"],
            "page_url": r["page_url"], "is_flagged": bool(r["is_flagged"]),
        })
    for r in challenge_rows:
        items.append({
            "kind": "challenge", "id": r["id"], "user_id": r["user_id"], "user_name": r["user_name"],
            "user_email": r["user_email"], "challenge_id": r["challenge_id"], "challenge_title": r["challenge_title"],
            "challenge_slug": r["challenge_slug"], "submission_id": r["submission_id"], "category": None,
            "rating": r["rating"], "rating_difficulty": r["rating_difficulty"], "rating_clarity": r["rating_clarity"],
            "message": r["message"], "status": "resolved" if r["admin_response"] else "new",
            "created_at": r["created_at"], "updated_at": r["updated_at"], "admin_response": r["admin_response"],
            "admin_responded_at": r["admin_responded_at"], "reply_emailed_at": r["reply_emailed_at"],
        })
    items.sort(key=lambda item: item["updated_at"] if item["kind"] == "challenge" else item["created_at"], reverse=True)
    return {"items": items[:limit]}


# ── Replies (daily routine; the founder approves each one) ──────────


def _reply(kind: str, feedback_id: str, body: FeedbackReplyRequest, principal: dict[str, Any]) -> dict:
    """Save an admin response and (optionally) email it through the tracked send path.

    With send_email the email goes first and the row is only updated once it is delivered to
    Resend, so a refused or failed send leaves the item in the unreplied inbox for a retry. The
    dedupe key hashes the message: retrying the same reply never sends twice, and a new message
    is a new email.
    """
    row = feedback_emails.load_feedback(kind, feedback_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    message = body.message
    email = feedback_emails.render_feedback_reply(
        kind=kind, user_name=row["user_name"], message=message, original=row["message"],
        challenge_title=row["challenge_title"],
    )
    digest = hashlib.sha256(message.encode("utf-8")).hexdigest()[:12]
    dedupe_key = f"feedback_reply:{kind}:{feedback_id}:{digest}"
    response: dict[str, Any] = {
        "ok": True, "kind": kind, "id": feedback_id, "dry_run": body.dry_run, "email_send_id": None,
        "email_status": None, "email_reason": None, "preview": {"subject": email["subject"], "text": email["text"]},
    }

    send_result: dict[str, Any] | None = None
    if body.send_email:
        send_result = send_tracked(
            user_id=row["user_id"], to=row["user_email"], template="feedback_reply",
            subject=email["subject"], html=email["html"], text=email["text"], stream="feedback",
            dedupe_key=dedupe_key, dry_run=body.dry_run, reply_to=settings.EMAIL_REPLY_TO or None,
            meta={"kind": kind, "feedback_id": feedback_id},
        )
        response["email_send_id"] = send_result["email_send_id"]
        response["email_status"] = send_result["status"]
        response["email_reason"] = send_result["reason"] or send_result["error"]

    if body.dry_run:
        return response

    delivered = send_result is not None and (
        send_result["status"] == "sent" or (send_result["status"] == "duplicate" and send_result["reason"] == "sent")
    )
    if body.send_email and not delivered:
        response["ok"] = False
        return response

    table = _KIND_TABLES[kind]
    updates = ["admin_response = ?", "admin_responded_by = ?", "admin_responded_at = datetime('now')"]
    params: list[Any] = [message, principal["id"]]
    if kind == "platform":
        if body.status:
            updates.append("status = ?")
            params.append(body.status)
        updates.append("updated_at = datetime('now')")
    if delivered:
        updates.append("reply_emailed_at = COALESCE(reply_emailed_at, datetime('now'))")
        updates.append("reply_email_send_id = COALESCE(?, reply_email_send_id)")
        params.append(send_result["email_send_id"] if send_result else None)
    params.append(feedback_id)
    execute(f"UPDATE {table} SET {', '.join(updates)} WHERE id = ?", tuple(params))

    _audit(principal, "reply_feedback", table, feedback_id, {
        "send_email": body.send_email,
        "email_status": response["email_status"],
        "email_send_id": response["email_send_id"],
        "status": body.status if kind == "platform" else None,
        "message_sha": digest,
    })
    return response


@router.post("/feedback/platform/{feedback_id}/reply")
def reply_platform_feedback(feedback_id: str, body: FeedbackReplyRequest, principal: FeedbackReplier) -> dict:
    return _reply("platform", feedback_id, body, principal)


@router.post("/feedback/challenges/{feedback_id}/reply")
def reply_challenge_feedback(feedback_id: str, body: FeedbackReplyRequest, principal: FeedbackReplier) -> dict:
    return _reply("challenge", feedback_id, body, principal)


# ── Challenge Feedback ──────────────────────────────────────────────


@router.get("/feedback/challenges")
def list_challenge_feedback(
    current_admin: AdminUser,
    challenge_id: Optional[str] = None,
    min_rating: Optional[int] = Query(None, ge=1, le=5),
    max_rating: Optional[int] = Query(None, ge=1, le=5),
    has_comment: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if challenge_id:
        conditions.append("cf.challenge_id = ?")
        params.append(challenge_id)
    if min_rating is not None:
        conditions.append("cf.rating_overall >= ?")
        params.append(min_rating)
    if max_rating is not None:
        conditions.append("cf.rating_overall <= ?")
        params.append(max_rating)
    if has_comment is True:
        conditions.append("cf.comment IS NOT NULL AND cf.comment != ''")
    elif has_comment is False:
        conditions.append("(cf.comment IS NULL OR cf.comment = '')")
    if search:
        conditions.append("(u.name LIKE ? OR u.email LIKE ? OR cf.comment LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT cf.*, u.name AS user_name, u.email AS user_email,
                   c.title AS challenge_title, c.slug AS challenge_slug
            FROM challenge_feedback cf
            JOIN users u ON cf.user_id = u.id
            JOIN challenges c ON cf.challenge_id = c.id
            WHERE {where}
            ORDER BY cf.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    total = fetch_one(
        f"""SELECT COUNT(*) AS count
            FROM challenge_feedback cf
            JOIN users u ON cf.user_id = u.id
            JOIN challenges c ON cf.challenge_id = c.id
            WHERE {where}""",
        tuple(count_params),
    )
    return {"items": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


# ── Platform Feedback ───────────────────────────────────────────────


@router.get("/feedback/platform")
def list_platform_feedback(
    current_admin: AdminUser,
    category: Optional[str] = None,
    fb_status: Optional[str] = Query(None, alias="status"),
    is_flagged: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if category:
        conditions.append("pf.category = ?")
        params.append(category)
    if fb_status:
        conditions.append("pf.status = ?")
        params.append(fb_status)
    if is_flagged is not None:
        conditions.append("pf.is_flagged = ?")
        params.append(1 if is_flagged else 0)
    if search:
        conditions.append("(u.name LIKE ? OR u.email LIKE ? OR pf.description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT pf.*, u.name AS user_name, u.email AS user_email
            FROM platform_feedback pf
            JOIN users u ON pf.user_id = u.id
            WHERE {where}
            ORDER BY pf.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    total = fetch_one(
        f"""SELECT COUNT(*) AS count
            FROM platform_feedback pf
            JOIN users u ON pf.user_id = u.id
            WHERE {where}""",
        tuple(count_params),
    )
    return {"items": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.put("/feedback/platform/{feedback_id}")
def update_platform_feedback(
    feedback_id: str,
    body: AdminFeedbackUpdate,
    current_admin: AdminUser,
) -> dict:
    """Update status, respond, or flag a platform feedback entry."""
    fb = fetch_one("SELECT * FROM platform_feedback WHERE id = ?", (feedback_id,))
    if fb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    updates = []
    params: list = []

    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status)
    if body.admin_response is not None:
        updates.append("admin_response = ?")
        params.append(body.admin_response)
        updates.append("admin_responded_by = ?")
        params.append(current_admin["id"])
        updates.append("admin_responded_at = datetime('now')")
    if body.is_flagged is not None:
        updates.append("is_flagged = ?")
        params.append(1 if body.is_flagged else 0)

    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(feedback_id)

    execute(
        f"UPDATE platform_feedback SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )

    row = fetch_one(
        """SELECT pf.*, u.name AS user_name, u.email AS user_email
           FROM platform_feedback pf
           JOIN users u ON pf.user_id = u.id
           WHERE pf.id = ?""",
        (feedback_id,),
    )
    return dict(row)


# ── Analytics ───────────────────────────────────────────────────────


@router.get("/feedback/analytics")
def feedback_analytics(current_admin: AdminUser) -> dict:
    """Aggregate feedback statistics."""
    # Per-challenge averages
    challenge_stats = fetch_all(
        """SELECT cf.challenge_id, c.title AS challenge_title, c.slug AS challenge_slug,
                  ROUND(AVG(cf.rating_overall), 2) AS avg_overall,
                  ROUND(AVG(cf.rating_difficulty), 2) AS avg_difficulty,
                  ROUND(AVG(cf.rating_clarity), 2) AS avg_clarity,
                  COUNT(*) AS total_count
           FROM challenge_feedback cf
           JOIN challenges c ON cf.challenge_id = c.id
           GROUP BY cf.challenge_id
           ORDER BY total_count DESC""",
        (),
    )

    # Platform feedback counts by category
    category_counts = fetch_all(
        "SELECT category, COUNT(*) AS count FROM platform_feedback GROUP BY category",
        (),
    )

    # Platform feedback counts by status
    status_counts = fetch_all(
        "SELECT status, COUNT(*) AS count FROM platform_feedback GROUP BY status",
        (),
    )

    # Totals
    cf_total = fetch_one("SELECT COUNT(*) AS count FROM challenge_feedback", ())
    pf_total = fetch_one("SELECT COUNT(*) AS count FROM platform_feedback", ())

    return {
        "challenge_feedback": {
            "total": cf_total["count"] if cf_total else 0,
            "per_challenge": challenge_stats,
        },
        "platform_feedback": {
            "total": pf_total["count"] if pf_total else 0,
            "by_category": {r["category"]: r["count"] for r in category_counts},
            "by_status": {r["status"]: r["count"] for r in status_counts},
        },
    }
