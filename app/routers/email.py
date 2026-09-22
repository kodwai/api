"""Public email endpoints (mounted under /api).

Routes:
  GET  /email/unsubscribe?u=&t=           shows a confirm button only; changes nothing, so mail
                                          scanners that pre-open links cannot unsubscribe anyone
  POST /email/unsubscribe/confirm?u=&t=   the button's target: unsubscribes, shows the result page
  POST /email/unsubscribe?u=&t=           RFC 8058 one-click unsubscribe (List-Unsubscribe-Post), empty 200

The token is stateless: HMAC-SHA256(UNSUBSCRIBE_SECRET, user_id), truncated (email_service).
Both POST routes set users.email_unsubscribed_at once; later clicks keep the original timestamp.
Unsubscribing stops lifecycle and feedback mail; account mail (password resets) still goes out.
"""
from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse, Response

from app.core.config import settings
from app.core.database import execute
from app.services.analytics_events import capture
from app.services.email_service import verify_unsubscribe_token

router = APIRouter(tags=["email"])

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{title}</title>
</head>
<body style="margin: 0; background: #faf8f5; color: #1f2937; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;">
<main style="max-width: 480px; margin: 12vh auto 0; padding: 0 16px; line-height: 1.55;">
<p style="font-family: Georgia, serif; font-size: 22px; margin: 0 0 24px;">kodwai</p>
<h1 style="font-size: 22px; margin: 0 0 12px;">{heading}</h1>
{body}
<p style="margin-top: 32px;"><a href="{home}" style="color: #b4441d;">Back to kodwai</a></p>
</main>
</body>
</html>
"""


def _page(title: str, heading: str, paragraphs: list[str], status_code: int = 200, extra_html: str = "") -> HTMLResponse:
    body = "\n".join(f"<p>{escape(p)}</p>" for p in paragraphs) + extra_html
    html = _PAGE.format(
        title=escape(title), heading=escape(heading), body=body, home=escape(settings.LANDING_URL, quote=True),
    )
    return HTMLResponse(html, status_code=status_code)


def _unsubscribe(user_id: str, via: str) -> None:
    execute(
        "UPDATE users SET email_unsubscribed_at = COALESCE(email_unsubscribed_at, datetime('now')) WHERE id = ?",
        (user_id,),
    )
    capture(user_id, "email_unsubscribed", {"via": via})


def _invalid_link() -> HTMLResponse:
    return _page(
        "Unsubscribe link not valid",
        "This unsubscribe link doesn't look right",
        [
            "Your email app may have cut it off. Reply to any email from me and I'll unsubscribe you by hand.",
            "Ege",
        ],
        status_code=400,
    )


@router.get("/email/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(u: str = Query(default="", max_length=64), t: str = Query(default="", max_length=64)) -> HTMLResponse:
    """Confirm step only. Link scanners (Safe Links and similar) open GET links before the
    reader does, so a GET must never unsubscribe."""
    if not verify_unsubscribe_token(u, t):
        return _invalid_link()
    action = escape(f"/api/email/unsubscribe/confirm?{urlencode({'u': u, 't': t})}", quote=True)
    button = (
        f'<form method="post" action="{action}" style="margin-top: 24px;">'
        '<button type="submit" style="font: inherit; padding: 10px 18px; border: 0; border-radius: 6px;'
        ' background: #1f2937; color: #faf8f5; cursor: pointer;">Unsubscribe</button></form>'
    )
    return _page(
        "Unsubscribe from kodwai emails",
        "Unsubscribe from kodwai emails?",
        ["You'll stop getting onboarding and product emails from kodwai. Emails you ask for, like password resets, still arrive."],
        extra_html=button,
    )


@router.post("/email/unsubscribe/confirm", response_class=HTMLResponse)
def unsubscribe_confirm(u: str = Query(default="", max_length=64), t: str = Query(default="", max_length=64)) -> HTMLResponse:
    if not verify_unsubscribe_token(u, t):
        return _invalid_link()
    _unsubscribe(u, "link")
    return _page(
        "Unsubscribed from kodwai emails",
        "You're unsubscribed",
        [
            "You won't get onboarding or product emails from kodwai anymore.",
            "Emails you ask for, like password resets, still arrive.",
        ],
    )


@router.post("/email/unsubscribe")
def unsubscribe_one_click(u: str = Query(default="", max_length=64), t: str = Query(default="", max_length=64)) -> Response:
    """One-click unsubscribe from the List-Unsubscribe header. Mail clients POST
    'List-Unsubscribe=One-Click'; the body is ignored, the query string carries the identity."""
    if not verify_unsubscribe_token(u, t):
        return Response(status_code=400)
    _unsubscribe(u, "one_click")
    return Response(status_code=200)
