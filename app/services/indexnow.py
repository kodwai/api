"""IndexNow pings for www.kodwai.com (Bing, Yandex, Seznam, Naver; Google does not take part).

Replaces the Google Indexing API call, which Google limits to JobPosting and BroadcastEvent
pages. ``notify`` is synchronous and never raises; request paths hand it to BackgroundTasks so
a slow endpoint never delays a response. The key file is served by the landing at
https://www.kodwai.com/<INDEXNOW_KEY>.txt, so only URLs on that host are sent.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings
from app.services.site_urls import CANONICAL_HOST, CANONICAL_SITE_URL

logger = logging.getLogger(__name__)

INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
# The protocol allows up to 10,000 URLs per request.
MAX_URLS = 10_000
TIMEOUT_SECONDS = 10.0


def build_payload(urls: list[str], key: str) -> dict[str, Any]:
    return {
        "host": CANONICAL_HOST,
        "key": key,
        "keyLocation": f"{CANONICAL_SITE_URL}/{key}.txt",
        "urlList": urls,
    }


def _eligible(urls: Iterable[str]) -> list[str]:
    """De-duplicated https URLs on the canonical host, in the order given."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if not url or url in seen:
            continue
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname != CANONICAL_HOST:
            logger.info("IndexNow: skipping %s (not on %s)", url, CANONICAL_HOST)
            continue
        seen.add(url)
        out.append(url)
    return out[:MAX_URLS]


def notify(urls: Iterable[str]) -> bool:
    """POST ``urls`` to IndexNow. Returns True when the endpoint accepted them (200 or 202).

    A no-op (False) when INDEXNOW_KEY is empty or no URL is on www.kodwai.com. Never raises.
    """
    try:
        key = (settings.INDEXNOW_KEY or "").strip()
        if not key:
            return False
        url_list = _eligible(urls)
        if not url_list:
            return False
        resp = httpx.post(
            INDEXNOW_ENDPOINT,
            json=build_payload(url_list, key),
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code in (200, 202):
            logger.info("IndexNow: submitted %d URL(s), status %s", len(url_list), resp.status_code)
            return True
        logger.warning("IndexNow: status %s for %d URL(s): %s", resp.status_code, len(url_list), resp.text[:200])
        return False
    except Exception:
        logger.exception("IndexNow: ping failed")
        return False
