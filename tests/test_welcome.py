"""First-login welcome flow: /auth/me welcomed flag + POST /auth/me/welcome."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import execute, fetch_one


def _developer(client: TestClient, email: str = "dev@test.com", username: str = "devuser") -> dict:
    resp = client.post("/api/auth/signup", json={
        "email": email, "password": "testpass123", "name": "Dev", "user_type": "developer", "username": username,
    })
    assert resp.status_code == 201, resp.text
    user = fetch_one("SELECT id FROM users WHERE email=?", (email,))
    execute("UPDATE users SET email_verified=1 WHERE id=?", (user["id"],))
    resp = client.post("/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_new_developer_not_welcomed(client):
    headers = _developer(client)
    assert client.get("/api/auth/me", headers=headers).json()["welcomed"] is False


def test_mark_welcome_sets_flag(client):
    headers = _developer(client)
    resp = client.post("/api/auth/me/welcome", headers=headers)
    assert resp.status_code == 204
    assert client.get("/api/auth/me", headers=headers).json()["welcomed"] is True


def test_mark_welcome_is_idempotent(client):
    headers = _developer(client)
    assert client.post("/api/auth/me/welcome", headers=headers).status_code == 204
    # A second call must not error and the flag stays set.
    assert client.post("/api/auth/me/welcome", headers=headers).status_code == 204
    assert client.get("/api/auth/me", headers=headers).json()["welcomed"] is True


def test_company_user_always_welcomed(client, auth_headers):
    # Company accounts have no welcome flow.
    assert client.get("/api/auth/me", headers=auth_headers).json()["welcomed"] is True
