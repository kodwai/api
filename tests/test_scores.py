"""Tests for scoring and comment endpoints."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.database import fetch_all, fetch_one


SAMPLE_PROJECT = {
    "title": "Score Test",
    "problem_statement_md": "# Test\n\nBuild something.",
    "time_limit_minutes": 30,
    "rubric": [
        {"name": "Code Quality", "weight": 8, "description": "Clean code"},
        {"name": "Problem Solving", "weight": 7, "description": "Effective approach"},
    ],
}


def _setup_completed_session(client: TestClient, headers: dict) -> str:
    """Create project, key, session, activate, end it. Return session_id."""
    project = client.post("/api/projects", headers=headers, json=SAMPLE_PROJECT).json()

    with patch("app.routers.api_keys._validate_anthropic_key", return_value=True):
        key = client.post("/api/api-keys", headers=headers, json={
            "key": "sk-ant-api03-scoretest12345",
            "label": "Score Key",
        }).json()

    session = client.post("/api/sessions", headers=headers, json={
        "project_id": project["id"],
        "api_key_id": key["id"],
        "candidate_name": "Score Candidate",
        "candidate_email": "score@test.com",
    }).json()

    # Activate
    token = session["session_token"]
    config = client.get(f"/api/sessions/{session['id']}/config?session_token={token}").json()
    secret = config["webhook_secret"]

    # End session (mock AI scoring so it doesn't call Anthropic)
    payload = {"end_reason": "completed"}
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    with patch("app.services.scoring_service.trigger_ai_scoring"):
        client.post(
            f"/api/sessions/{session['id']}/end",
            content=body,
            headers={"X-Kodwai-Signature": f"sha256={sig}", "Content-Type": "application/json"},
        )

    return session["id"]


# ── Scores ──────────────────────────────────────────────────


def test_list_scores_empty(client: TestClient, auth_headers):
    session_id = _setup_completed_session(client, auth_headers)
    resp = client.get(f"/api/sessions/{session_id}/scores", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_manual_score(client: TestClient, auth_headers):
    session_id = _setup_completed_session(client, auth_headers)
    resp = client.post(f"/api/sessions/{session_id}/scores", headers=auth_headers, json={
        "dimensions": [
            {"name": "Code Quality", "score": 8, "max_score": 10, "justification": "Clean"},
            {"name": "Problem Solving", "score": 7, "max_score": 10, "justification": "Good"},
        ],
        "overall_score": 7.5,
        "summary": "Good candidate",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["score_type"] == "manual"
    assert data["overall_score"] == 7.5
    assert len(data["dimensions"]) == 2


def test_list_scores_with_data(client: TestClient, auth_headers):
    session_id = _setup_completed_session(client, auth_headers)
    client.post(f"/api/sessions/{session_id}/scores", headers=auth_headers, json={
        "dimensions": [{"name": "Code", "score": 8, "max_score": 10}],
        "overall_score": 8,
    })

    resp = client.get(f"/api/sessions/{session_id}/scores", headers=auth_headers)
    assert len(resp.json()) == 1


def test_trigger_ai_scoring(client: TestClient, auth_headers):
    session_id = _setup_completed_session(client, auth_headers)

    with patch("app.routers.scores.trigger_ai_scoring", return_value="score-id-123") as mock:
        # Pre-insert a fake AI score so the endpoint can fetch it
        import secrets
        from app.core.database import execute
        score_id = secrets.token_hex(16)
        execute(
            """INSERT INTO scores (id, session_id, score_type, dimensions, overall_score, summary)
               VALUES (?, ?, 'ai', '[]', 8.0, 'Test')""",
            (score_id, session_id),
        )

        resp = client.post(f"/api/sessions/{session_id}/scores/trigger-ai", headers=auth_headers)
        assert resp.status_code == 201
        mock.assert_called_once_with(session_id)


def test_trigger_ai_scoring_not_completed(client: TestClient, auth_headers):
    """Can't trigger AI scoring on a non-completed session."""
    project = client.post("/api/projects", headers=auth_headers, json=SAMPLE_PROJECT).json()

    with patch("app.routers.api_keys._validate_anthropic_key", return_value=True):
        key = client.post("/api/api-keys", headers=auth_headers, json={
            "key": "sk-ant-api03-scoretest99999",
            "label": "Key",
        }).json()

    session = client.post("/api/sessions", headers=auth_headers, json={
        "project_id": project["id"],
        "api_key_id": key["id"],
        "candidate_name": "Pending",
        "candidate_email": "pending@test.com",
    }).json()

    resp = client.post(f"/api/sessions/{session['id']}/scores/trigger-ai", headers=auth_headers)
    assert resp.status_code == 400


def test_scores_cross_org(client: TestClient, auth_headers, second_user_headers):
    session_id = _setup_completed_session(client, auth_headers)
    resp = client.get(f"/api/sessions/{session_id}/scores", headers=second_user_headers)
    assert resp.status_code == 404


# ── Comments ────────────────────────────────────────────────


def test_create_comment(client: TestClient, auth_headers):
    session_id = _setup_completed_session(client, auth_headers)
    resp = client.post(f"/api/sessions/{session_id}/comments", headers=auth_headers, json={
        "content": "Great candidate!",
    })
    assert resp.status_code == 201
    assert resp.json()["content"] == "Great candidate!"


def test_list_comments(client: TestClient, auth_headers):
    session_id = _setup_completed_session(client, auth_headers)
    client.post(f"/api/sessions/{session_id}/comments", headers=auth_headers, json={"content": "Comment 1"})
    client.post(f"/api/sessions/{session_id}/comments", headers=auth_headers, json={"content": "Comment 2"})

    resp = client.get(f"/api/sessions/{session_id}/comments", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_delete_own_comment(client: TestClient, auth_headers):
    session_id = _setup_completed_session(client, auth_headers)
    comment = client.post(f"/api/sessions/{session_id}/comments", headers=auth_headers, json={
        "content": "To delete",
    }).json()

    resp = client.delete(f"/api/sessions/{session_id}/comments/{comment['id']}", headers=auth_headers)
    assert resp.status_code == 204

    resp = client.get(f"/api/sessions/{session_id}/comments", headers=auth_headers)
    assert len(resp.json()) == 0


def test_comments_cross_org(client: TestClient, auth_headers, second_user_headers):
    session_id = _setup_completed_session(client, auth_headers)
    resp = client.get(f"/api/sessions/{session_id}/comments", headers=second_user_headers)
    assert resp.status_code == 404
