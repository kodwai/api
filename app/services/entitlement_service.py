"""Developer free-submission entitlement.

Single source of truth for "may this developer submit a challenge, and whose
Anthropic key pays for the AI scoring?". Read by the auth `/me` endpoint (so the
web app and CLI can gate the UI), by the challenge start/submit endpoints (server
side enforcement), and indirectly by scoring (which reads the recorded key_source).

A developer gets ``FREE_SUBMISSION_LIMIT`` submissions scored with the platform's
own key (``PLATFORM_ANTHROPIC_API_KEY``). After that they must connect their own
key, which then scores unlimited submissions. A free credit is consumed by a
submission whose ``key_source`` is ``'platform'`` (reserved at submit time).
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.database import execute, fetch_one
from app.services.auth_service import has_claude_api_key

# Key sources recorded on submissions.key_source
KEY_SOURCE_USER = "user"
KEY_SOURCE_PLATFORM = "platform"


def platform_key_available() -> bool:
    """Whether the platform has its own Anthropic key configured for the free tier."""
    return bool(settings.PLATFORM_ANTHROPIC_API_KEY)


def free_limit() -> int:
    """Free submissions granted per developer, or 0 when the free tier is off."""
    return settings.FREE_SUBMISSION_LIMIT if platform_key_available() else 0


def free_submissions_used(user_id: str) -> int:
    """Free credits this developer has spent (monotonic; deleting a submission never refunds)."""
    row = fetch_one(
        "SELECT free_submissions_used FROM developer_profiles WHERE user_id = ?",
        (user_id,),
    )
    return int(row["free_submissions_used"]) if row and row["free_submissions_used"] is not None else 0


def consume_free_credit(user_id: str) -> None:
    """Permanently spend one free credit. Called at submit time for platform-scored submissions."""
    execute(
        "UPDATE developer_profiles SET free_submissions_used = free_submissions_used + 1, "
        "updated_at = datetime('now') WHERE user_id = ?",
        (user_id,),
    )


def get_entitlement(user: dict[str, Any]) -> dict[str, Any]:
    """Resolve a user's submission entitlement.

    The free tier only applies to developer accounts; company accounts use their
    organization's keys for interview sessions and are always allowed here.
    """
    if user.get("user_type") != "developer":
        return {
            "free_submissions_used": 0,
            "free_submissions_limit": 0,
            "free_submissions_remaining": 0,
            "can_submit": True,
        }

    limit = free_limit()
    used = free_submissions_used(user["id"])
    remaining = max(0, limit - used)
    can_submit = has_claude_api_key(user) or remaining > 0
    return {
        "free_submissions_used": used,
        "free_submissions_limit": limit,
        "free_submissions_remaining": remaining,
        "can_submit": can_submit,
    }


def decide_key_source(user: dict[str, Any]) -> str | None:
    """Pick which key should pay for this developer's next submission.

    Returns ``'user'`` (own connected key, unlimited), ``'platform'`` (consumes a
    free credit), or ``None`` when the developer has neither — the caller should
    then refuse the submission and prompt them to connect a key.
    """
    if has_claude_api_key(user):
        return KEY_SOURCE_USER
    if platform_key_available() and free_submissions_used(user["id"]) < free_limit():
        return KEY_SOURCE_PLATFORM
    return None
