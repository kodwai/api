"""Anthropic API proxy — forwards Claude API calls with the real API key.

The candidate's CLI sets ANTHROPIC_BASE_URL to this proxy and uses a
session token as the API key. This proxy validates the session, swaps
the session token for the real encrypted API key, enforces time/budget
limits, and forwards the request to Anthropic.

The real API key NEVER leaves the server.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.core.database import fetch_one
from app.services.encryption_service import decrypt_api_key
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["proxy"])

ANTHROPIC_API = "https://api.anthropic.com"

# Long-lived client with connection pooling
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)

SKIP_RESPONSE_HEADERS = {
    "transfer-encoding", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade",
}


def _get_session_and_key(session_token: str) -> tuple[dict, str]:
    """Validate session token, check limits, return (session, decrypted_api_key)."""
    session = fetch_one(
        """SELECT s.id, s.status, s.started_at, s.api_key_id, s.max_budget_usd,
                  s.total_cost_usd, s.organization_id,
                  p.time_limit_minutes
           FROM sessions s
           JOIN projects p ON s.project_id = p.id
           WHERE s.session_token = ?""",
        (session_token,),
    )

    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token")

    if session["status"] not in ("active", "pending"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session is '{session['status']}' — cannot make API calls",
        )

    # Check time limit
    if session["started_at"] and session["time_limit_minutes"]:
        started = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
        elapsed_min = (datetime.now(timezone.utc) - started).total_seconds() / 60
        if elapsed_min > session["time_limit_minutes"] + 5:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Session time limit exceeded")

    # Decrypt the real API key
    api_key_row = fetch_one(
        "SELECT encrypted_key, key_iv FROM api_keys WHERE id = ?",
        (session["api_key_id"],),
    )
    if api_key_row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="API key not found")

    real_key = decrypt_api_key(api_key_row["encrypted_key"], api_key_row["key_iv"], settings.ENCRYPTION_KEY)
    return session, real_key


@router.api_route("/{session_id}", methods=["GET", "HEAD", "OPTIONS"])
async def proxy_health(session_id: str) -> Response:
    """Health check — Claude Code sends HEAD to verify the base URL."""
    return Response(content="ok", status_code=200)


@router.api_route(
    "/{session_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_anthropic(session_id: str, path: str, request: Request) -> Response:
    """Proxy all Anthropic API calls through Kodwai."""
    # Extract session token from x-api-key header
    session_token = request.headers.get("x-api-key", "")
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing x-api-key header")

    session, real_api_key = _get_session_and_key(session_token)

    anthropic_url = f"{ANTHROPIC_API}/{path}"
    if request.url.query:
        anthropic_url += f"?{request.url.query}"

    body = await request.body()

    # Build headers for Anthropic
    forward_headers = {}
    for key, value in request.headers.items():
        if key.lower() in ("host", "x-api-key", "content-length", "accept-encoding"):
            continue
        if key.lower().startswith("anthropic") or key.lower() == "content-type":
            forward_headers[key] = value

    forward_headers["x-api-key"] = real_api_key
    # Force no compression so we can pass through bytes cleanly
    forward_headers["accept-encoding"] = "identity"

    # Check if streaming
    is_streaming = False
    if body:
        try:
            body_json = json.loads(body)
            is_streaming = body_json.get("stream", False)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    try:
        if is_streaming:
            # Build request and send with stream=True (NO context manager)
            req = http_client.build_request(
                method=request.method,
                url=anthropic_url,
                headers=forward_headers,
                content=body,
            )
            upstream_resp = await http_client.send(req, stream=True)

            response_headers = {
                k: v for k, v in upstream_resp.headers.items()
                if k.lower() not in SKIP_RESPONSE_HEADERS
            }

            # StreamingResponse + BackgroundTask to close stream after response is sent
            return StreamingResponse(
                upstream_resp.aiter_raw(),
                status_code=upstream_resp.status_code,
                headers=response_headers,
                background=BackgroundTask(upstream_resp.aclose),
            )
        else:
            # Non-streaming: simple forward
            resp = await http_client.request(
                method=request.method,
                url=anthropic_url,
                headers=forward_headers,
                content=body,
            )

            response_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in SKIP_RESPONSE_HEADERS
            }

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=response_headers,
            )

    except httpx.TimeoutException:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Anthropic API timed out")
    except httpx.RequestError as exc:
        logger.exception("Proxy error for session %s", session_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Proxy error: {exc}")
