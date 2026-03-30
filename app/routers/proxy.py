"""Anthropic API proxy — forwards Claude API calls with the real API key.

The candidate's CLI sets ANTHROPIC_BASE_URL to this proxy and uses a
session token as the API key. This proxy validates the session, swaps
the session token for the real encrypted API key, enforces time/budget
limits, and forwards the request to Anthropic.

The real API key NEVER leaves the server.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.database import fetch_one
from app.services.encryption_service import decrypt_api_key
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["proxy"])

# Anthropic API base
ANTHROPIC_API = "https://api.anthropic.com"

# Headers to forward from the client
FORWARD_HEADERS = [
    "content-type",
    "anthropic-version",
    "anthropic-beta",
    "x-api-key",  # We'll replace this
]

# Headers NOT to forward back (hop-by-hop)
SKIP_RESPONSE_HEADERS = {
    "transfer-encoding", "connection", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade",
}


def _get_session_and_key(session_token: str) -> tuple[dict, str]:
    """Validate session token, check limits, return (session, decrypted_api_key).

    Raises HTTPException if invalid.
    """
    # Find session by token (the CLI sends the session_token as x-api-key)
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token",
        )

    if session["status"] not in ("active", "pending"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Session is '{session['status']}' — cannot make API calls",
        )

    # Check time limit
    if session["started_at"] and session["time_limit_minutes"]:
        started = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
        elapsed_min = (datetime.now(timezone.utc) - started).total_seconds() / 60
        if elapsed_min > session["time_limit_minutes"] + 5:  # 5 min grace
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session time limit exceeded",
            )

    # Decrypt the real API key
    api_key_row = fetch_one(
        "SELECT encrypted_key, key_iv FROM api_keys WHERE id = ?",
        (session["api_key_id"],),
    )
    if api_key_row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not found",
        )

    real_key = decrypt_api_key(
        api_key_row["encrypted_key"],
        api_key_row["key_iv"],
        settings.ENCRYPTION_KEY,
    )

    return session, real_key


@router.api_route(
    "/{session_id}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
)
async def proxy_anthropic(session_id: str, path: str, request: Request) -> Response:
    """Proxy all Anthropic API calls through Kodwai.

    The CLI sets:
      ANTHROPIC_BASE_URL=https://api.kodwai.com/proxy/{session_id}
      ANTHROPIC_API_KEY=<session_token>

    This endpoint:
    1. Extracts the session token from x-api-key header
    2. Validates the session is active and within time limits
    3. Swaps the session token for the real API key
    4. Forwards the request to Anthropic
    5. Returns the response
    """
    # Extract session token from the x-api-key header
    session_token = request.headers.get("x-api-key", "")
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing x-api-key header",
        )

    # Validate session and get real key
    session, real_api_key = _get_session_and_key(session_token)

    # Build the Anthropic URL
    anthropic_url = f"{ANTHROPIC_API}/{path}"

    # Read request body
    body = await request.body()

    # Build headers for Anthropic
    forward_headers = {}
    for key, value in request.headers.items():
        if key.lower() in ("host", "x-api-key", "content-length"):
            continue
        if key.lower().startswith("anthropic") or key.lower() == "content-type":
            forward_headers[key] = value

    # Set the real API key
    forward_headers["x-api-key"] = real_api_key

    # Check if this is a streaming request
    is_streaming = False
    if body:
        try:
            import json
            body_json = json.loads(body)
            is_streaming = body_json.get("stream", False)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    try:
        if is_streaming:
            # Stream the response back to the client
            async def stream_response():
                async with httpx.AsyncClient(timeout=300.0) as client:
                    async with client.stream(
                        method=request.method,
                        url=anthropic_url,
                        headers=forward_headers,
                        content=body,
                    ) as resp:
                        yield resp.status_code, dict(resp.headers)
                        async for chunk in resp.aiter_bytes():
                            yield chunk

            # We need to handle streaming differently
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    method=request.method,
                    url=anthropic_url,
                    headers=forward_headers,
                    content=body,
                ) as anthropic_resp:
                    response_headers = {}
                    for key, value in anthropic_resp.headers.items():
                        if key.lower() not in SKIP_RESPONSE_HEADERS:
                            response_headers[key] = value

                    async def generate():
                        async for chunk in anthropic_resp.aiter_bytes():
                            yield chunk

                    from starlette.responses import StreamingResponse
                    return StreamingResponse(
                        generate(),
                        status_code=anthropic_resp.status_code,
                        headers=response_headers,
                    )
        else:
            # Non-streaming: simple forward
            async with httpx.AsyncClient(timeout=300.0) as client:
                anthropic_resp = await client.request(
                    method=request.method,
                    url=anthropic_url,
                    headers=forward_headers,
                    content=body,
                )

            # Build response headers
            response_headers = {}
            for key, value in anthropic_resp.headers.items():
                if key.lower() not in SKIP_RESPONSE_HEADERS:
                    response_headers[key] = value

            return Response(
                content=anthropic_resp.content,
                status_code=anthropic_resp.status_code,
                headers=response_headers,
            )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Anthropic API request timed out",
        )
    except httpx.RequestError as exc:
        logger.exception("Proxy error for session %s", session_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to reach Anthropic API: {exc}",
        )
