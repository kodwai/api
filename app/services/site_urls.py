"""Public URLs on the landing site (www.kodwai.com is canonical; the apex redirects to it)."""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings

CANONICAL_HOST = "www.kodwai.com"
CANONICAL_SITE_URL = f"https://{CANONICAL_HOST}"


def site_url() -> str:
    """LANDING_URL without a trailing slash, with the bare apex upgraded to the www host.

    An explicit LANDING_URL=https://kodwai.com in an environment would otherwise put
    redirecting URLs into RSS and IndexNow pings. Other hosts (localhost, previews) pass through.
    """
    parts = urlsplit(settings.LANDING_URL.strip().rstrip("/"))
    if parts.hostname == "kodwai.com":
        return CANONICAL_SITE_URL
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")) or CANONICAL_SITE_URL


def blog_post_url(slug: str) -> str:
    return f"{site_url()}/blog/{slug}"
