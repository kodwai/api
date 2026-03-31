"""Anthropic API proxy — forwards Claude API calls with the real API key.

The candidate's CLI sets ANTHROPIC_BASE_URL to this proxy and uses a
session token as the API key. This proxy validates the session, swaps
the session token for the real encrypted API key, enforces time/budget
limits, and forwards the request to Anthropic.

The real API key NEVER leaves the server.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from app.core.database import execute, fetch_one
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

# ── Cost tracking ───────────────────────────────────

# In-memory cost tracker (fast path for budget checks)
_session_costs: dict[str, float] = defaultdict(float)

# Prices per token (USD)
MODEL_PRICES: dict[str, dict[str, float]] = {
    # Sonnet
    "claude-sonnet-4-6-20250514": {"input": 3.0 / 1e6, "output": 15.0 / 1e6, "cache_write": 3.75 / 1e6, "cache_read": 0.30 / 1e6},
    "claude-sonnet-4-5-20250514": {"input": 3.0 / 1e6, "output": 15.0 / 1e6, "cache_write": 3.75 / 1e6, "cache_read": 0.30 / 1e6},
    # Opus
    "claude-opus-4-6-20250514": {"input": 15.0 / 1e6, "output": 75.0 / 1e6, "cache_write": 18.75 / 1e6, "cache_read": 1.50 / 1e6},
    # Haiku
    "claude-haiku-4-5-20241022": {"input": 0.80 / 1e6, "output": 4.0 / 1e6, "cache_write": 1.0 / 1e6, "cache_read": 0.08 / 1e6},
}

# Default prices if model not in table (use Sonnet pricing as safe default)
_DEFAULT_PRICES = {"input": 3.0 / 1e6, "output": 15.0 / 1e6, "cache_write": 3.75 / 1e6, "cache_read": 0.30 / 1e6}


def _get_model_prices(model: str) -> dict[str, float]:
    """Get per-token prices for a model. Falls back to Sonnet pricing."""
    if model in MODEL_PRICES:
        return MODEL_PRICES[model]
    # Try prefix match (model IDs often have date suffixes)
    for key, prices in MODEL_PRICES.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return prices
    return _DEFAULT_PRICES


def _calculate_cost(model: str, usage: dict) -> float:
    """Calculate USD cost from usage data."""
    prices = _get_model_prices(model)
    return (
        usage.get("input_tokens", 0) * prices["input"]
        + usage.get("output_tokens", 0) * prices["output"]
        + usage.get("cache_creation_input_tokens", 0) * prices["cache_write"]
        + usage.get("cache_read_input_tokens", 0) * prices["cache_read"]
    )


def _persist_cost(session_id: str, cost: float) -> None:
    """Update session cost in DB (fire-and-forget from background thread)."""
    try:
        execute(
            "UPDATE sessions SET total_cost_usd = COALESCE(total_cost_usd, 0) + ? WHERE id = ?",
            (cost, session_id),
        )
    except Exception:
        logger.exception("Failed to persist cost for session %s", session_id)


# ── Session validation ──────────────────────────────


def _get_session_and_key(session_token: str, model: str | None = None) -> tuple[dict, str]:
    """Validate session token, check limits, return (session, decrypted_api_key)."""
    session = fetch_one(
        """SELECT s.id, s.status, s.started_at, s.api_key_id, s.max_budget_usd,
                  s.total_cost_usd, s.organization_id,
                  p.time_limit_minutes, p.max_budget_usd as project_budget_usd,
                  p.allowed_tools as p_allowed_tools
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

    # Check budget limit (pre-request)
    budget_limit = session["max_budget_usd"] or session["project_budget_usd"]
    if budget_limit:
        # Use in-memory tracker (fast) with DB value as baseline
        current_cost = _session_costs.get(session["id"], session["total_cost_usd"] or 0)
        if current_cost >= budget_limit:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Session budget exceeded (${current_cost:.2f} / ${budget_limit:.2f})",
            )

    # Decrypt the real API key
    api_key_row = fetch_one(
        "SELECT encrypted_key, key_iv FROM api_keys WHERE id = ?",
        (session["api_key_id"],),
    )
    if api_key_row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="API key not found")

    real_key = decrypt_api_key(api_key_row["encrypted_key"], api_key_row["key_iv"], settings.ENCRYPTION_KEY)
    return session, real_key


# ── Proxy endpoints ─────────────────────────────────


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
    forward_headers["accept-encoding"] = "identity"

    # Detect streaming and model
    is_streaming = False
    model = "claude-sonnet-4-6-20250514"
    if body:
        try:
            body_json = json.loads(body)
            is_streaming = body_json.get("stream", False)
            model = body_json.get("model", model)
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

    try:
        if is_streaming:
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

            # Wrap the stream to parse SSE events for cost tracking
            async def tracked_stream():
                usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
                buffer = ""

                async for chunk in upstream_resp.aiter_raw():
                    yield chunk

                    # Parse SSE lines for usage data
                    try:
                        text = chunk.decode("utf-8", errors="ignore")
                        buffer += text
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line.startswith("data: "):
                                continue
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                continue
                            try:
                                data = json.loads(data_str)
                                if data.get("type") == "message_start":
                                    msg_usage = data.get("message", {}).get("usage", {})
                                    usage["input_tokens"] = msg_usage.get("input_tokens", 0)
                                    usage["cache_creation_input_tokens"] = msg_usage.get("cache_creation_input_tokens", 0)
                                    usage["cache_read_input_tokens"] = msg_usage.get("cache_read_input_tokens", 0)
                                elif data.get("type") == "message_delta":
                                    delta_usage = data.get("usage", {})
                                    usage["output_tokens"] = delta_usage.get("output_tokens", 0)
                            except json.JSONDecodeError:
                                pass
                    except Exception:
                        pass

                # After stream ends, calculate and persist cost
                cost = _calculate_cost(model, usage)
                if cost > 0:
                    _session_costs[session["id"]] = _session_costs.get(session["id"], session["total_cost_usd"] or 0) + cost
                    import threading
                    threading.Thread(target=_persist_cost, args=(session["id"], cost), daemon=True).start()
                    logger.info("Session %s: +$%.4f (in: %d, out: %d)", session["id"], cost, usage["input_tokens"], usage["output_tokens"])

            async def cleanup():
                await upstream_resp.aclose()

            return StreamingResponse(
                tracked_stream(),
                status_code=upstream_resp.status_code,
                headers=response_headers,
                background=BackgroundTask(cleanup),
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

            # Track cost from non-streaming response
            if resp.status_code == 200:
                try:
                    resp_json = json.loads(resp.content)
                    usage = resp_json.get("usage", {})
                    resp_model = resp_json.get("model", model)
                    cost = _calculate_cost(resp_model, usage)
                    if cost > 0:
                        _session_costs[session["id"]] = _session_costs.get(session["id"], session["total_cost_usd"] or 0) + cost
                        import threading
                        threading.Thread(target=_persist_cost, args=(session["id"], cost), daemon=True).start()
                        logger.info("Session %s: +$%.4f (in: %d, out: %d)", session["id"], cost, usage.get("input_tokens", 0), usage.get("output_tokens", 0))
                except (json.JSONDecodeError, KeyError):
                    pass

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
