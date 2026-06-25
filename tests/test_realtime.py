"""Tests for historical events endpoint."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

from fastapi.testclient import TestClient


SAMPLE_PROJECT = {
    "title": "Realtime Test",
    "problem_statement_md": "# Test\n\nBuild something.",
    "time_limit_minutes": 30,
    "rubric": [{"name": "Code Quality", "weight": 8, "description": "Clean code"}],
}


def _setup(client: TestClient, headers: dict) -> tuple[str, str, str]:
    """Create project, key, session. Return (session_id, webhook_secret, session_token)."""
    project = client.post("/api/projects", headers=headers, json=SAMPLE_PROJECT).json()

    with patch("app.routers.api_keys._validate_anthropic_key", return_value=True):
        key = client.post("/api/api-keys", headers=headers, json={
            "key": "sk-ant-api03-realtimetest123",
            "label": "RT Key",
        }).json()

    session = client.post("/api/sessions", headers=headers, json={
        "project_id": project["id"],
        "api_key_id": key["id"],
        "candidate_name": "RT Candidate",
        "candidate_email": "rt@test.com",
    }).json()

    token = session["session_token"]
    config = client.get(f"/api/sessions/{session['id']}/config?session_token={token}").json()

    return session["id"], config["webhook_secret"], token


def _sign(payload: dict, secret: str) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, f"sha256={sig}"


def test_list_session_events_empty(client: TestClient, auth_headers):
    session_id, _, _ = _setup(client, auth_headers)
    resp = client.get(f"/api/sessions/{session_id}/events", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["events"] == []


def test_list_session_events_with_data(client: TestClient, auth_headers):
    session_id, secret, _ = _setup(client, auth_headers)

    for i in range(3):
        payload = {"event_type": "assistant", "data": {"n": i}, "timestamp": f"2026-01-01T00:00:0{i}Z"}
        body, sig = _sign(payload, secret)
        client.post(
            f"/api/sessions/{session_id}/events",
            content=body,
            headers={"X-Kodwai-Signature": sig, "Content-Type": "application/json"},
        )

    resp = client.get(f"/api/sessions/{session_id}/events", headers=auth_headers)
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) == 3
    assert events[0]["type"] == "assistant"


def test_list_session_events_parses_json_data(client: TestClient, auth_headers):
    session_id, secret, _ = _setup(client, auth_headers)

    payload = {"event_type": "prompt", "data": {"content": "hello"}}
    body, sig = _sign(payload, secret)
    client.post(
        f"/api/sessions/{session_id}/events",
        content=body,
        headers={"X-Kodwai-Signature": sig, "Content-Type": "application/json"},
    )

    resp = client.get(f"/api/sessions/{session_id}/events", headers=auth_headers)
    events = resp.json()["events"]
    assert events[0]["data"]["content"] == "hello"


def test_list_session_events_cross_org(client: TestClient, auth_headers, second_user_headers):
    session_id, _, _ = _setup(client, auth_headers)
    resp = client.get(f"/api/sessions/{session_id}/events", headers=second_user_headers)
    assert resp.status_code == 404
