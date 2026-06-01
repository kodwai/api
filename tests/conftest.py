"""Shared fixtures for all tests."""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

# Override env before importing app
os.environ.update({
    "TURSO_DATABASE_URL": "file::memory:",
    "TURSO_AUTH_TOKEN": "",
    "JWT_SECRET": "test-secret-key-for-testing-only",
    "ENCRYPTION_KEY": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "RESEND_API_KEY": "",
    "CORS_ORIGINS": "http://localhost:3000",
    "CLIENT_URL": "http://localhost:3000",
    "APP_URL": "http://localhost:8000",
    # Skip seeding default projects in tests that assert exact project counts.
    # The dedicated test in test_auth.py clears this for its own signup.
    "KODWAI_DISABLE_DEFAULT_PROJECTS": "1",
    # Free tier off by default in tests (don't inherit a real key from .env.local).
    # Tests that exercise the free tier monkeypatch this to a dummy value.
    "PLATFORM_ANTHROPIC_API_KEY": "",
    "FREE_SUBMISSION_LIMIT": "3",
})

from app.core.database import connect, disconnect, run_migrations, get_connection, execute, fetch_one
from app.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    """Give every test a fresh in-memory database."""
    connect()
    run_migrations()
    yield
    conn = get_connection()
    conn.execute("PRAGMA foreign_keys = OFF")
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
    ).fetchall()]
    for t in tables:
        conn.execute(f"DROP TABLE IF EXISTS [{t}]")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    disconnect()


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


def _create_verified_user(client: TestClient, email: str, password: str, name: str, org_name: str) -> dict[str, str]:
    """Sign up, verify email, login, return auth headers."""
    resp = client.post("/api/auth/signup", json={
        "email": email,
        "password": password,
        "name": name,
        "organization_name": org_name,
    })
    assert resp.status_code == 201

    # Manually verify email in DB
    user = fetch_one("SELECT id, email_verification_token FROM users WHERE email = ?", (email,))
    execute("UPDATE users SET email_verified = 1, email_verification_token = NULL WHERE id = ?", (user["id"],))

    # Login
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    """Sign up a verified test user and return auth headers."""
    return _create_verified_user(client, "admin@test.com", "testpass123", "Test Admin", "Test Org")


@pytest.fixture
def second_user_headers(client: TestClient) -> dict[str, str]:
    """Sign up a second verified user in a different org."""
    return _create_verified_user(client, "other@test.com", "testpass123", "Other User", "Other Org")
