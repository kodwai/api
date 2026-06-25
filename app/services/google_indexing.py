"""Google Indexing API integration for blog post indexing."""
from __future__ import annotations

import base64
import json
import logging
import urllib.request

logger = logging.getLogger(__name__)


def notify_url_updated(url: str) -> None:
    """Notify Google Indexing API that a URL has been updated.

    Uses a service account for authentication. Fails silently with logging.
    """
    from app.core.config import settings

    if not settings.GOOGLE_SERVICE_ACCOUNT_JSON:
        logger.info("Google Indexing: GOOGLE_SERVICE_ACCOUNT_JSON not set, skipping indexing for %s", url)
        return

    try:
        sa_json = base64.b64decode(settings.GOOGLE_SERVICE_ACCOUNT_JSON)
        sa_info = json.loads(sa_json)
    except Exception:
        logger.error("Google Indexing: Failed to decode service account JSON")
        return

    try:
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/indexing"],
        )
        credentials.refresh(google.auth.transport.requests.Request())
        access_token = credentials.token
    except Exception:
        # Fallback: try using google.auth directly
        try:
            import google.auth.transport.requests
            from google.oauth2 import service_account as sa

            creds = sa.Credentials.from_service_account_info(
                sa_info,
                scopes=["https://www.googleapis.com/auth/indexing"],
            )
            request = google.auth.transport.requests.Request()
            creds.refresh(request)
            access_token = creds.token
        except Exception as e:
            logger.error("Google Indexing: Failed to authenticate: %s", e)
            return

    body = json.dumps({"url": url, "type": "URL_UPDATED"}).encode("utf-8")
    req = urllib.request.Request(
        "https://indexing.googleapis.com/v3/urlNotifications:publish",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info("Google Indexing: Submitted %s — status %s", url, resp.status)
    except Exception as e:
        logger.error("Google Indexing: Failed to submit %s — %s", url, e)
