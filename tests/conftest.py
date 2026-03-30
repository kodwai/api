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
})

from app.core.database import connect, disconnect, run_migrations, get_connection
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


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    """Sign up a test user and return auth headers."""
    resp = client.post("/api/auth/signup", json={
        "email": "admin@test.com",
        "password": "testpass123",
        "name": "Test Admin",
        "organization_name": "Test Org",
    })
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_user_headers(client: TestClient) -> dict[str, str]:
    """Sign up a second user in a different org."""
    resp = client.post("/api/auth/signup", json={
        "email": "other@test.com",
        "password": "testpass123",
        "name": "Other User",
        "organization_name": "Other Org",
    })
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
