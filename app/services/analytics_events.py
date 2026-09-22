"""Server-side PostHog capture for funnel events the browser never sees (emails sent, scores landed).

``capture`` is fire-and-forget: a no-op when POSTHOG_PROJECT_KEY is empty, it never raises, and
the HTTP call runs in a daemon thread so it stays off the request path (like email_service).
The client identifies users by user id, so pass the user id as ``distinct_id`` to join the funnel.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 5.0


def _post(url: str, payload: dict[str, Any]) -> None:
    try:
        resp = httpx.post(url, json=payload, timeout=_TIMEOUT_SECONDS)
        if resp.status_code >= 400:
            logger.warning("PostHog capture %s returned %s", payload.get("event"), resp.status_code)
    except Exception as e:
        logger.warning("PostHog capture %s failed: %s", payload.get("event"), e)


def capture(distinct_id: str | None, event: str, properties: dict[str, Any] | None = None) -> None:
    """Send one event to PostHog in the background. Never raises."""
    try:
        if not settings.POSTHOG_PROJECT_KEY or not distinct_id or not event:
            return
        payload = {
            "api_key": settings.POSTHOG_PROJECT_KEY,
            "event": event,
            "distinct_id": str(distinct_id),
            "properties": {**(properties or {}), "$lib": "kodwai-api", "source": "server"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        url = f"{settings.POSTHOG_HOST.rstrip('/')}/i/v0/e/"
        threading.Thread(target=_post, args=(url, payload), daemon=True).start()
    except Exception:
        logger.exception("PostHog capture %s could not be queued", event)
