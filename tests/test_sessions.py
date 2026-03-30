"""Session endpoint tests."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.database import fetch_one


SAMPLE_PROJECT = {
    "title": "Test Challenge",
    "problem_statement_md": "# Test\n\nBuild something.",
    "time_limit_minutes": 30,
    "rubric": [{"name": "Code Quality", "weight": 8, "description": "Clean code"}],
}


def _setup_project_and_key(client: TestClient, headers: dict) -> tuple[str, str]:
    """Create a project and API key, return their IDs."""
    resp = client.post("/api/projects", headers=headers, json=SAMPLE_PROJECT)
    assert resp.status_code == 201, f"Project creation failed: {resp.json()}"
    project = resp.json()

    with patch("app.routers.api_keys._validate_anthropic_key", return_value=True):
        key = client.post("/api/api-keys", headers=headers, json={
            "key": "sk-ant-api03-testkey1234567890",
            "label": "Test Key",
        }).json()

    return project["id"], key["id"]


def _create_session(client: TestClient, headers: dict, project_id: str, key_id: str, **overrides) -> dict:
    data = {
        "project_id": project_id,
        "api_key_id": key_id,
        "candidate_name": "Jane Doe",
        "candidate_email": "jane@example.com",
        **overrides,
    }
    resp = client.post("/api/sessions", headers=headers, json=data)
    assert resp.status_code == 201
    return resp.json()


def _sign_payload(payload: dict, secret: str) -> tuple[str, str]:
    """Sign a payload and return (body_str, signature)."""
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, f"sha256={sig}"


# ── Create Session ──────────────────────────────────────────


def test_create_session(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    assert session["status"] == "pending"
    assert session["candidate_name"] == "Jane Doe"
    assert session["candidate_email"] == "jane@example.com"
    assert session["project_title"] == "Test Challenge"
    assert "id" in session
    assert "session_token" in session


def test_create_session_invalid_project(client: TestClient, auth_headers):
    _, key_id = _setup_project_and_key(client, auth_headers)
    resp = client.post("/api/sessions", headers=auth_headers, json={
        "project_id": "nonexistent",
        "api_key_id": key_id,
        "candidate_name": "Jane",
        "candidate_email": "jane@test.com",
    })
    assert resp.status_code == 404


def test_create_session_invalid_key(client: TestClient, auth_headers):
    project_id, _ = _setup_project_and_key(client, auth_headers)
    resp = client.post("/api/sessions", headers=auth_headers, json={
        "project_id": project_id,
        "api_key_id": "nonexistent",
        "candidate_name": "Jane",
        "candidate_email": "jane@test.com",
    })
    assert resp.status_code == 404


def test_create_session_cross_org(client: TestClient, auth_headers, second_user_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    resp = client.post("/api/sessions", headers=second_user_headers, json={
        "project_id": project_id,
        "api_key_id": key_id,
        "candidate_name": "Jane",
        "candidate_email": "jane@test.com",
    })
    assert resp.status_code == 404


# ── List Sessions ───────────────────────────────────────────


def test_list_sessions(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    _create_session(client, auth_headers, project_id, key_id, candidate_name="Alice")
    _create_session(client, auth_headers, project_id, key_id, candidate_name="Bob")

    resp = client.get("/api/sessions", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_sessions_filter_by_project(client: TestClient, auth_headers):
    p1, key_id = _setup_project_and_key(client, auth_headers)
    p2 = client.post("/api/projects", headers=auth_headers, json={
        **SAMPLE_PROJECT, "title": "Other Project"
    }).json()["id"]

    _create_session(client, auth_headers, p1, key_id)
    _create_session(client, auth_headers, p2, key_id)

    resp = client.get(f"/api/sessions?project_id={p1}", headers=auth_headers)
    assert len(resp.json()) == 1
    assert resp.json()[0]["project_id"] == p1


def test_list_sessions_cross_org(client: TestClient, auth_headers, second_user_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    _create_session(client, auth_headers, project_id, key_id)

    resp = client.get("/api/sessions", headers=second_user_headers)
    assert len(resp.json()) == 0


# ── Get Session ─────────────────────────────────────────────


def test_get_session(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    resp = client.get(f"/api/sessions/{session['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["candidate_name"] == "Jane Doe"


def test_get_session_not_found(client: TestClient, auth_headers):
    resp = client.get("/api/sessions/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


# ── Session Config (Public) ─────────────────────────────────


def test_get_session_config(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    token = session["session_token"]
    resp = client.get(f"/api/sessions/{session['id']}/config?session_token={token}")
    assert resp.status_code == 200

    config = resp.json()
    assert config["session_id"] == session["id"]
    assert config["project_title"] == "Test Challenge"
    assert config["problem_statement_md"] == "# Test\n\nBuild something."
    assert config["time_limit_minutes"] == 30
    assert config["api_key"].endswith("7890")  # decrypted key
    assert config["webhook_secret"] is not None
    assert len(config["rubric"]) == 1

    # Session should now be active
    s = fetch_one("SELECT status FROM sessions WHERE id = ?", (session["id"],))
    assert s["status"] == "active"


def test_get_session_config_wrong_token(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    resp = client.get(f"/api/sessions/{session['id']}/config?session_token=wrong")
    assert resp.status_code == 404


def test_get_session_config_already_active(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    token = session["session_token"]
    # First call activates
    client.get(f"/api/sessions/{session['id']}/config?session_token={token}")
    # Second call should fail
    resp = client.get(f"/api/sessions/{session['id']}/config?session_token={token}")
    assert resp.status_code == 400


# ── Session Events (HMAC) ──────────────────────────────────


def test_post_session_event(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    # Activate session first
    token = session["session_token"]
    config = client.get(f"/api/sessions/{session['id']}/config?session_token={token}").json()
    secret = config["webhook_secret"]

    payload = {"event_type": "prompt", "data": {"content": "Hello Claude"}}
    body, sig = _sign_payload(payload, secret)

    resp = client.post(
        f"/api/sessions/{session['id']}/events",
        content=body,
        headers={"X-Kodwai-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "stored"


def test_post_session_event_bad_signature(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    payload = {"event_type": "prompt", "data": {"content": "Hello"}}
    body = json.dumps(payload).encode()

    resp = client.post(
        f"/api/sessions/{session['id']}/events",
        content=body,
        headers={"X-Kodwai-Signature": "sha256=wrong", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


def test_post_session_event_no_signature(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    resp = client.post(
        f"/api/sessions/{session['id']}/events",
        content=b'{"event_type": "prompt"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


# ── Session Files (HMAC) ───────────────────────────────────


def test_post_session_file(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    token = session["session_token"]
    config = client.get(f"/api/sessions/{session['id']}/config?session_token={token}").json()
    secret = config["webhook_secret"]

    payload = {
        "file_path": "src/main.ts",
        "content": "console.log('hello')",
        "change_type": "create",
    }
    body, sig = _sign_payload(payload, secret)

    resp = client.post(
        f"/api/sessions/{session['id']}/files",
        content=body,
        headers={"X-Kodwai-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 201


# ── End Session (HMAC) ─────────────────────────────────────


def test_end_session(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    token = session["session_token"]
    config = client.get(f"/api/sessions/{session['id']}/config?session_token={token}").json()
    secret = config["webhook_secret"]

    payload = {
        "end_reason": "candidate_finished",
        "total_cost_usd": 0.42,
        "total_tokens": 15000,
    }
    body, sig = _sign_payload(payload, secret)

    resp = client.post(
        f"/api/sessions/{session['id']}/end",
        content=body,
        headers={"X-Kodwai-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"

    # Verify in DB
    s = fetch_one("SELECT * FROM sessions WHERE id = ?", (session["id"],))
    assert s["status"] == "completed"
    assert s["end_reason"] == "candidate_finished"
    assert s["total_cost_usd"] == 0.42


def test_end_session_already_completed(client: TestClient, auth_headers):
    project_id, key_id = _setup_project_and_key(client, auth_headers)
    session = _create_session(client, auth_headers, project_id, key_id)

    token = session["session_token"]
    config = client.get(f"/api/sessions/{session['id']}/config?session_token={token}").json()
    secret = config["webhook_secret"]

    payload = {"end_reason": "completed"}
    body, sig = _sign_payload(payload, secret)

    # End once
    client.post(
        f"/api/sessions/{session['id']}/end",
        content=body,
        headers={"X-Kodwai-Signature": sig, "Content-Type": "application/json"},
    )

    # End again — should fail
    body, sig = _sign_payload(payload, secret)
    resp = client.post(
        f"/api/sessions/{session['id']}/end",
        content=body,
        headers={"X-Kodwai-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
