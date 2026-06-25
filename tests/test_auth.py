"""Auth endpoint tests."""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.core.database import execute, fetch_all, fetch_one
from app.services.default_projects import DEFAULT_PROJECTS


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
    assert "message" in data
    assert "access_token" not in data  # No token until verified


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
    assert user["email_verified"] == 0

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


# ── Default projects seeded on company signup ───────────────


def test_signup_seeds_default_projects(client: TestClient):
    """A new company gets its own copies of every default project, fully editable."""
    os.environ.pop("KODWAI_DISABLE_DEFAULT_PROJECTS", None)
    try:
        client.post("/api/auth/signup", json={
            "email": "seed@test.com",
            "password": "testpass123",
            "name": "Seed User",
            "organization_name": "Seed Org",
        })

        user = fetch_one("SELECT id, organization_id FROM users WHERE email = ?", ("seed@test.com",))
        assert user is not None
        org_id = user["organization_id"]

        rows = fetch_all(
            "SELECT id, title, difficulty FROM projects WHERE organization_id = ? AND is_archived = 0",
            (org_id,),
        )
        assert len(rows) == len(DEFAULT_PROJECTS)

        seeded_titles = {r["title"] for r in rows}
        expected_titles = {p["title"] for p in DEFAULT_PROJECTS}
        assert seeded_titles == expected_titles

        # Each org owns its own copy; ids are not shared with the template constants.
        assert all(len(r["id"]) == 32 for r in rows)
    finally:
        os.environ["KODWAI_DISABLE_DEFAULT_PROJECTS"] = "1"


def test_seeded_projects_are_editable_and_deletable(client: TestClient):
    """The owning org can edit and archive its seeded defaults like any other project."""
    os.environ.pop("KODWAI_DISABLE_DEFAULT_PROJECTS", None)
    try:
        client.post("/api/auth/signup", json={
            "email": "editor@test.com",
            "password": "testpass123",
            "name": "Editor",
            "organization_name": "Editor Org",
        })

        user = fetch_one(
            "SELECT id, organization_id FROM users WHERE email = ?",
            ("editor@test.com",),
        )
        execute(
            "UPDATE users SET email_verified = 1, email_verification_token = NULL WHERE id = ?",
            (user["id"],),
        )
        login = client.post("/api/auth/login", json={"email": "editor@test.com", "password": "testpass123"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        projects = client.get("/api/projects", headers=headers).json()
        assert len(projects) == len(DEFAULT_PROJECTS)

        # Edit one default project
        target = projects[0]
        edit = client.put(
            f"/api/projects/{target['id']}",
            headers=headers,
            json={"title": "Renamed by Org"},
        )
        assert edit.status_code == 200
        assert edit.json()["title"] == "Renamed by Org"

        # Delete (archive) another
        victim = projects[1]
        delete = client.delete(f"/api/projects/{victim['id']}", headers=headers)
        assert delete.status_code == 204

        after = client.get("/api/projects", headers=headers).json()
        assert len(after) == len(DEFAULT_PROJECTS) - 1
        assert all(p["id"] != victim["id"] for p in after)
    finally:
        os.environ["KODWAI_DISABLE_DEFAULT_PROJECTS"] = "1"


def test_signup_seeding_does_not_leak_across_orgs(client: TestClient):
    """Each org's seeded projects are scoped to that org only."""
    os.environ.pop("KODWAI_DISABLE_DEFAULT_PROJECTS", None)
    try:
        client.post("/api/auth/signup", json={
            "email": "org1@test.com",
            "password": "testpass123",
            "name": "Org1",
            "organization_name": "Org One",
        })
        client.post("/api/auth/signup", json={
            "email": "org2@test.com",
            "password": "testpass123",
            "name": "Org2",
            "organization_name": "Org Two",
        })

        u1 = fetch_one("SELECT organization_id FROM users WHERE email = ?", ("org1@test.com",))
        u2 = fetch_one("SELECT organization_id FROM users WHERE email = ?", ("org2@test.com",))
        assert u1["organization_id"] != u2["organization_id"]

        r1 = fetch_all(
            "SELECT id FROM projects WHERE organization_id = ? AND is_archived = 0",
            (u1["organization_id"],),
        )
        r2 = fetch_all(
            "SELECT id FROM projects WHERE organization_id = ? AND is_archived = 0",
            (u2["organization_id"],),
        )
        assert len(r1) == len(DEFAULT_PROJECTS)
        assert len(r2) == len(DEFAULT_PROJECTS)
        assert {r["id"] for r in r1}.isdisjoint({r["id"] for r in r2})
    finally:
        os.environ["KODWAI_DISABLE_DEFAULT_PROJECTS"] = "1"


# ── Login ───────────────────────────────────────────────────


def test_login_success(client: TestClient, auth_headers):
    # auth_headers fixture already verified + logged in, just test again
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


def test_login_nonexistent_email(client: TestClient):
    resp = client.post("/api/auth/login", json={
        "email": "nobody@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 401


def test_login_unverified_email(client: TestClient):
    """Unverified users cannot login."""
    client.post("/api/auth/signup", json={
        "email": "unverified@test.com",
        "password": "testpass123",
        "name": "Unverified",
        "organization_name": "Org",
    })
    resp = client.post("/api/auth/login", json={
        "email": "unverified@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 403
    assert "verify" in resp.json()["detail"].lower()


# ── Me ──────────────────────────────────────────────────────


def test_get_me(client: TestClient, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@test.com"
    assert data["name"] == "Test Admin"
    assert data["role"] == "admin"
    assert "password" not in data
    assert "password_hash" not in data


def test_get_me_no_token(client: TestClient):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_get_me_invalid_token(client: TestClient):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401


# ── Email Verification ──────────────────────────────────────


def test_verify_email(client: TestClient):
    client.post("/api/auth/signup", json={
        "email": "verify@test.com",
        "password": "testpass123",
        "name": "Verify Me",
        "organization_name": "Org",
    })

    user = fetch_one("SELECT * FROM users WHERE email = ?", ("verify@test.com",))
    assert user["email_verified"] == 0
    token = user["email_verification_token"]
    assert token is not None

    resp = client.get(f"/api/auth/verify-email?token={token}")
    assert resp.status_code == 200

    user = fetch_one("SELECT * FROM users WHERE email = ?", ("verify@test.com",))
    assert user["email_verified"] == 1

    # Now login should work
    resp = client.post("/api/auth/login", json={
        "email": "verify@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_verify_email_invalid_token(client: TestClient):
    resp = client.get("/api/auth/verify-email?token=bogus")
    assert resp.status_code == 400


# ── Logout ──────────────────────────────────────────────────


def test_logout(client: TestClient):
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 204
