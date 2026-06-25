"""Organization endpoint tests."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import execute, fetch_one


# ── Get Organization ────────────────────────────────────────


def test_get_my_org(client: TestClient, auth_headers):
    resp = client.get("/api/organizations/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test Org"
    assert "id" in data
    assert "created_at" in data


def test_get_my_org_unauthenticated(client: TestClient):
    resp = client.get("/api/organizations/me")
    assert resp.status_code == 401


# ── Update Organization ─────────────────────────────────────


def test_update_org_name(client: TestClient, auth_headers):
    resp = client.put("/api/organizations/me", headers=auth_headers, json={
        "name": "Updated Org",
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Org"


def test_update_org_no_fields(client: TestClient, auth_headers):
    resp = client.put("/api/organizations/me", headers=auth_headers, json={})
    assert resp.status_code == 400


def test_update_org_non_admin_forbidden(client: TestClient, auth_headers):
    # Get the user and change their role to interviewer
    user = fetch_one("SELECT * FROM users WHERE email = ?", ("admin@test.com",))
    execute("UPDATE users SET role = 'interviewer' WHERE id = ?", (user["id"],))

    resp = client.put("/api/organizations/me", headers=auth_headers, json={
        "name": "Hacked",
    })
    assert resp.status_code == 403


# ── List Members ────────────────────────────────────────────


def test_list_members(client: TestClient, auth_headers):
    resp = client.get("/api/organizations/me/members", headers=auth_headers)
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["email"] == "admin@test.com"
    assert members[0]["role"] == "admin"


# ── Invitations ─────────────────────────────────────────────


def test_create_invitation(client: TestClient, auth_headers):
    resp = client.post("/api/organizations/me/invitations", headers=auth_headers, json={
        "email": "newmember@test.com",
        "role": "interviewer",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "newmember@test.com"
    assert data["role"] == "interviewer"
    assert data["status"] == "pending"


def test_create_invitation_duplicate_member(client: TestClient, auth_headers):
    resp = client.post("/api/organizations/me/invitations", headers=auth_headers, json={
        "email": "admin@test.com",
        "role": "interviewer",
    })
    assert resp.status_code == 409


def test_create_invitation_duplicate_pending(client: TestClient, auth_headers):
    client.post("/api/organizations/me/invitations", headers=auth_headers, json={
        "email": "newmember@test.com",
        "role": "interviewer",
    })
    resp = client.post("/api/organizations/me/invitations", headers=auth_headers, json={
        "email": "newmember@test.com",
        "role": "viewer",
    })
    assert resp.status_code == 409


def test_create_invitation_invalid_role(client: TestClient, auth_headers):
    resp = client.post("/api/organizations/me/invitations", headers=auth_headers, json={
        "email": "newmember@test.com",
        "role": "superadmin",
    })
    assert resp.status_code == 422


# ── Update Member Role ──────────────────────────────────────


def test_update_member_role(client: TestClient, auth_headers):
    # Create a second user in the same org via direct DB insert
    import secrets
    from app.core.security import hash_password

    me = fetch_one("SELECT * FROM users WHERE email = ?", ("admin@test.com",))
    member_id = secrets.token_hex(16)
    execute(
        """INSERT INTO users (id, email, password_hash, name, role, organization_id, email_verified)
           VALUES (?, ?, ?, ?, 'interviewer', ?, 1)""",
        (member_id, "member@test.com", hash_password("pass1234"), "Member", me["organization_id"]),
    )

    resp = client.put(f"/api/organizations/me/members/{member_id}", headers=auth_headers, json={
        "role": "viewer",
    })
    assert resp.status_code == 200
    assert resp.json()["role"] == "viewer"


def test_cannot_change_own_role(client: TestClient, auth_headers):
    me = fetch_one("SELECT * FROM users WHERE email = ?", ("admin@test.com",))
    resp = client.put(f"/api/organizations/me/members/{me['id']}", headers=auth_headers, json={
        "role": "viewer",
    })
    assert resp.status_code == 400


# ── Remove Member ───────────────────────────────────────────


def test_remove_member(client: TestClient, auth_headers):
    import secrets
    from app.core.security import hash_password

    me = fetch_one("SELECT * FROM users WHERE email = ?", ("admin@test.com",))
    member_id = secrets.token_hex(16)
    execute(
        """INSERT INTO users (id, email, password_hash, name, role, organization_id, email_verified)
           VALUES (?, ?, ?, ?, 'viewer', ?, 1)""",
        (member_id, "remove@test.com", hash_password("pass1234"), "ToRemove", me["organization_id"]),
    )

    resp = client.delete(f"/api/organizations/me/members/{member_id}", headers=auth_headers)
    assert resp.status_code == 204

    assert fetch_one("SELECT * FROM users WHERE id = ?", (member_id,)) is None


def test_cannot_remove_self(client: TestClient, auth_headers):
    me = fetch_one("SELECT * FROM users WHERE email = ?", ("admin@test.com",))
    resp = client.delete(f"/api/organizations/me/members/{me['id']}", headers=auth_headers)
    assert resp.status_code == 400


def test_remove_nonexistent_member(client: TestClient, auth_headers):
    resp = client.delete("/api/organizations/me/members/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


# ── Cross-Org Isolation ─────────────────────────────────────


def test_cannot_see_other_org_members(client: TestClient, auth_headers, second_user_headers):
    resp1 = client.get("/api/organizations/me/members", headers=auth_headers)
    resp2 = client.get("/api/organizations/me/members", headers=second_user_headers)

    emails1 = {m["email"] for m in resp1.json()}
    emails2 = {m["email"] for m in resp2.json()}

    assert "admin@test.com" in emails1
    assert "admin@test.com" not in emails2
    assert "other@test.com" in emails2
    assert "other@test.com" not in emails1
