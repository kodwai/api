"""Feedback email: founder replies, the instant acknowledgment, and the founder notification.

Founder-voice mail signed "Hakan", in the shared layout (email_layout). Every user-supplied value is
escaped in the HTML part,
and the user's original text is quoted back so a reply has context. No em dashes in any copy.

Templates (``email_sends.template``):
  feedback_reply         a founder-approved reply (admin API); not flag-gated
  feedback_ack           instant acknowledgment to the user; gated by feedback_ack_emails
  feedback_ack_founder   notification to EMAIL_REPLY_TO; gated by feedback_ack_emails
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import settings
from app.core.database import fetch_one
from app.services.email_layout import Block, FooterLine, Link, P, Quote, Small, render
from app.services.email_service import send_tracked
from app.services.feature_flags import flag_active_by_key

logger = logging.getLogger(__name__)

ACK_FLAG = "feedback_ack_emails"
FEEDBACK_KINDS: tuple[str, ...] = ("platform", "challenge")
# Long originals are cut when quoted back; the full text stays in the admin inbox.
MAX_QUOTE_CHARS = 1500

CATEGORY_LABELS = {
    "bug_report": "Bug report",
    "feature_request": "Feature request",
    "general": "General",
    "improvement": "Improvement",
}

FOOTER = "You're getting this because you sent feedback on kodwai."


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _header_safe(value: str | None, limit: int = 120) -> str:
    """Collapse whitespace (no CR/LF in a subject) and cap the length."""
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 3].rstrip() + "..."


def _first_name(name: str | None) -> str:
    parts = (name or "").strip().split()
    if not parts or "@" in parts[0]:
        return ""
    return parts[0]


def _greeting(name: str | None) -> str:
    first = _first_name(name)
    return f"Hi {first}," if first else "Hi there,"


def _clip(text: str | None) -> str:
    text = (text or "").strip()
    return text if len(text) <= MAX_QUOTE_CHARS else text[:MAX_QUOTE_CHARS].rstrip() + " [...]"


def _message_blocks(text: str) -> list[Block]:
    """One paragraph block per blank-line-separated paragraph of an approved message."""
    return [P(block.strip()) for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]


def _signed(message: str) -> bool:
    """True when the message already ends with Hakan's sign-off, so it is not added twice."""
    lines = [line for line in message.strip().splitlines() if line.strip()]
    return bool(lines) and re.sub(r"[^a-z]", "", lines[-1].lower()) == "hakan"


def _has_greeting(message: str) -> bool:
    return bool(re.match(r"(hi|hey|hello|dear)\b", message.strip(), re.IGNORECASE))


def _about(kind: str, challenge_title: str | None) -> str:
    if kind == "challenge" and challenge_title:
        return _header_safe(challenge_title, 80)
    return "kodwai"


def _you_wrote(quoted: str) -> list[Block]:
    return [Small("You wrote:"), Quote(quoted)] if quoted else []


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def render_feedback_reply(
    *,
    kind: str,
    user_name: str | None,
    message: str,
    original: str | None,
    challenge_title: str | None = None,
) -> dict[str, str]:
    """The founder's reply. ``message`` is the approved reply body; greeting and sign-off are
    added unless the message already has them. Returns {subject, text, html}."""
    body = message.strip()
    subject = f"Re: your feedback on {_about(kind, challenge_title)}"
    text, html = render(
        subject=subject,
        preheader=_header_safe(body, 110),
        greeting=None if _has_greeting(body) else _greeting(user_name),
        blocks=_message_blocks(body),
        signature=None if _signed(body) else "Hakan",
        after=_you_wrote(_clip(original)),
        footer=[FooterLine(f"{FOOTER} Reply to this email and it comes straight to me.")],
    )
    return {"subject": subject, "text": text, "html": html}


def render_feedback_ack(
    *,
    kind: str,
    user_name: str | None,
    original: str | None,
    challenge_title: str | None = None,
) -> dict[str, str]:
    """Instant, non-LLM acknowledgment sent right after feedback is submitted."""
    about = _about(kind, challenge_title)
    subject = f"Thanks for the feedback on {about}"
    text, html = render(
        subject=subject,
        preheader="I read every message myself and usually reply within a day.",
        greeting=_greeting(user_name),
        blocks=[
            P("Thanks for taking the time to write this. I read every message myself, and I usually get "
              "back to people within a day."),
            P("If you think of anything else, just reply to this email."),
        ],
        after=_you_wrote(_clip(original)),
        footer=[FooterLine(FOOTER)],
    )
    return {"subject": subject, "text": text, "html": html}


def render_founder_notification(
    *,
    kind: str,
    feedback_id: str,
    user_name: str | None,
    user_email: str | None,
    original: str | None,
    category: str | None = None,
    rating: int | None = None,
    page_url: str | None = None,
    challenge_title: str | None = None,
) -> dict[str, str]:
    """Short heads-up to the founder's inbox. Replies should go through the admin inbox so they
    are tracked, which is why this mail's reply-to stays the founder's own address."""
    who = _header_safe(user_name, 60) or "someone"
    if kind == "challenge":
        title = _header_safe(challenge_title, 80) or "a challenge"
        rated = f" ({rating}/5)" if rating else ""
        subject = f"[feedback] {title}{rated} from {who}"
        opener = f"New challenge feedback on {title} from {who} <{user_email or 'unknown'}>."
    else:
        label = CATEGORY_LABELS.get(category or "", category or "Feedback")
        subject = f"[feedback] {label} from {who}"
        opener = f"New platform feedback ({label}) from {who} <{user_email or 'unknown'}>."

    details: list[str] = []
    if rating:
        details.append(f"Rating: {rating}/5")
    if page_url:
        details.append(f"Page: {page_url}")
    inbox_url = f"{settings.CLIENT_URL.rstrip('/')}/admin/feedback"
    quoted = _clip(original)

    blocks: list[Block] = [P(opener)]
    if details:
        blocks.append(Small("\n".join(details)))
    if quoted:
        blocks.append(Quote(quoted))
    blocks += [
        Link("Reply from the admin inbox", inbox_url),
        Small(f"Replying there keeps the reply tracked. Feedback id: {kind}/{feedback_id}"),
    ]
    text, html = render(
        subject=subject,
        preheader=_header_safe(original, 110),
        blocks=blocks,
        signature=None,
        footer=[FooterLine("Internal notification for the kodwai team.")],
    )
    return {"subject": subject, "text": text, "html": html}


# ---------------------------------------------------------------------------
# Loading and sending
# ---------------------------------------------------------------------------

def load_feedback(kind: str, feedback_id: str) -> dict[str, Any] | None:
    """One feedback row with the user and (for challenge feedback) the challenge, normalized so
    both kinds share keys: message, rating, category, status."""
    if kind == "platform":
        return fetch_one(
            """SELECT pf.id, pf.user_id, u.name AS user_name, u.email AS user_email,
                      NULL AS challenge_id, NULL AS challenge_title, NULL AS submission_id,
                      pf.category, pf.rating, pf.description AS message, pf.status, pf.page_url,
                      pf.admin_response, pf.reply_emailed_at, pf.created_at
               FROM platform_feedback pf JOIN users u ON u.id = pf.user_id
               WHERE pf.id = ?""",
            (feedback_id,),
        )
    if kind == "challenge":
        return fetch_one(
            """SELECT cf.id, cf.user_id, u.name AS user_name, u.email AS user_email,
                      cf.challenge_id, c.title AS challenge_title, cf.submission_id,
                      NULL AS category, cf.rating_overall AS rating, cf.comment AS message,
                      NULL AS status, NULL AS page_url,
                      cf.admin_response, cf.reply_emailed_at, cf.created_at
               FROM challenge_feedback cf
               JOIN users u ON u.id = cf.user_id
               JOIN challenges c ON c.id = cf.challenge_id
               WHERE cf.id = ?""",
            (feedback_id,),
        )
    raise ValueError(f"Unknown feedback kind: {kind}")


def acknowledgments_enabled() -> bool:
    """Cheap pre-check before queueing: the kill switch is on and the sender config is present.
    send_tracked re-checks all of this, so a race with a flag flip still sends nothing."""
    return bool(
        settings.RESEND_API_KEY
        and settings.EMAIL_FROM_LIFECYCLE
        and settings.EMAIL_REPLY_TO
        and flag_active_by_key(ACK_FLAG)
    )


def send_feedback_acknowledgments(kind: str, feedback_id: str) -> dict[str, Any]:
    """Send the user acknowledgment and the founder notification for one feedback row.

    Each is deduped per row (feedback_ack:<kind>:<id>, feedback_ack_founder:<kind>:<id>), so an
    edited challenge rating never acknowledges twice. Never raises; returns the two send results
    (or {"skipped": reason}) for logging and tests.
    """
    try:
        if not acknowledgments_enabled():
            return {"skipped": "disabled"}
        row = load_feedback(kind, feedback_id)
        if row is None:
            return {"skipped": "not_found"}
        if not (row.get("message") or "").strip():
            # A bare star rating has nothing to reply to.
            return {"skipped": "no_message"}

        results: dict[str, Any] = {}
        ack = render_feedback_ack(
            kind=kind, user_name=row["user_name"], original=row["message"], challenge_title=row["challenge_title"],
        )
        results["ack"] = send_tracked(
            user_id=row["user_id"], to=row["user_email"], template="feedback_ack",
            subject=ack["subject"], html=ack["html"], text=ack["text"], stream="feedback",
            dedupe_key=f"feedback_ack:{kind}:{feedback_id}", meta={"kind": kind, "feedback_id": feedback_id},
        )

        note = render_founder_notification(
            kind=kind, feedback_id=feedback_id, user_name=row["user_name"], user_email=row["user_email"],
            original=row["message"], category=row["category"], rating=row["rating"],
            page_url=row["page_url"], challenge_title=row["challenge_title"],
        )
        results["founder"] = send_tracked(
            user_id=None, to=settings.EMAIL_REPLY_TO, template="feedback_ack_founder",
            subject=note["subject"], html=note["html"], text=note["text"], stream="feedback",
            dedupe_key=f"feedback_ack_founder:{kind}:{feedback_id}", meta={"kind": kind, "feedback_id": feedback_id},
        )
        return results
    except Exception:
        logger.exception("Feedback acknowledgment for %s/%s failed", kind, feedback_id)
        return {"skipped": "error"}
