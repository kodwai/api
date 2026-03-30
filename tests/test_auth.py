"""Auth endpoint tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import fetch_one


# ── Signup ──────────────────────────────────────────────────


def test_signup_success(client: TestClient):
    resp = client.post("/api/auth/signup", json={
        "email": "new@test.com",
        "password": "testpass123",
        "name": "New User",
        "organization_name": "New Org",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_signup_creates_org_and_admin_user(client: TestClient):
    client.post("/api/auth/signup", json={
        "email": "new@test.com",
        "password": "testpass123",
        "name": "New User",
        "organization_name": "New Org",
    })
    user = fetch_one("SELECT * FROM users WHERE email = ?", ("new@test.com",))
    assert user is not None
    assert user["role"] == "admin"
    assert user["name"] == "New User"

    org = fetch_one("SELECT * FROM organizations WHERE id = ?", (user["organization_id"],))
    assert org is not None
    assert org["name"] == "New Org"


def test_signup_duplicate_email(client: TestClient):
    client.post("/api/auth/signup", json={
        "email": "dup@test.com",
        "password": "testpass123",
        "name": "User",
        "organization_name": "Org",
    })
    resp = client.post("/api/auth/signup", json={
        "email": "dup@test.com",
        "password": "testpass456",
        "name": "User 2",
        "organization_name": "Org 2",
    })
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"]


def test_signup_short_password(client: TestClient):
    resp = client.post("/api/auth/signup", json={
        "email": "new@test.com",
        "password": "short",
        "name": "User",
        "organization_name": "Org",
    })
    assert resp.status_code == 422


def test_signup_invalid_email(client: TestClient):
    resp = client.post("/api/auth/signup", json={
        "email": "not-an-email",
        "password": "testpass123",
        "name": "User",
        "organization_name": "Org",
    })
    assert resp.status_code == 422


def test_signup_missing_fields(client: TestClient):
    resp = client.post("/api/auth/signup", json={
        "email": "new@test.com",
    })
    assert resp.status_code == 422


# ── Login ───────────────────────────────────────────────────


def test_login_success(client: TestClient, auth_headers):
    resp = client.post("/api/auth/login", json={
        "email": "admin@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(client: TestClient, auth_headers):
    resp = client.post("/api/auth/login", json={
        "email": "admin@test.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


def test_login_nonexistent_email(client: TestClient):
    resp = client.post("/api/auth/login", json={
        "email": "nobody@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 401


# ── Me ──────────────────────────────────────────────────────


def test_get_me(client: TestClient, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@test.com"
    assert data["name"] == "Test Admin"
    assert data["role"] == "admin"
    assert "organization_id" in data
    assert "password" not in data
    assert "password_hash" not in data


def test_get_me_no_token(client: TestClient):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_get_me_invalid_token(client: TestClient):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


# ── Email Verification ──────────────────────────────────────


def test_verify_email(client: TestClient, auth_headers):
    user = fetch_one("SELECT * FROM users WHERE email = ?", ("admin@test.com",))
    assert user["email_verified"] == 0
    token = user["email_verification_token"]
    assert token is not None

    resp = client.get(f"/api/auth/verify-email?token={token}")
    assert resp.status_code == 200

    user = fetch_one("SELECT * FROM users WHERE email = ?", ("admin@test.com",))
    assert user["email_verified"] == 1
    assert user["email_verification_token"] is None


def test_verify_email_invalid_token(client: TestClient):
    resp = client.get("/api/auth/verify-email?token=bogus")
    assert resp.status_code == 400


# ── Logout ──────────────────────────────────────────────────


def test_logout(client: TestClient):
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 204
