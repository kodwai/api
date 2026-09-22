"""Regression: /api/admin/challenges must require a superadmin, not role='admin'.

Every signup is stored with role='admin', so a role check lets any logged-in
user list drafts and hidden test suites, and create, edit or delete challenges.
"""
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


CHALLENGE = {
    "title": "Guard Test",
    "slug": "guard-test",
    "description": "d",
    "problem_statement_md": "# p",
    "difficulty": "easy",
    "category": "backend",
}


def test_developer_cannot_list_admin_challenges(client):
    headers = _developer(client)
    assert client.get("/api/admin/challenges", headers=headers).status_code in (401, 403)


def test_developer_cannot_create_admin_challenge(client):
    headers = _developer(client)
    assert client.post("/api/admin/challenges", headers=headers, json=CHALLENGE).status_code in (401, 403)
    assert fetch_one("SELECT id FROM challenges WHERE slug = ?", ("guard-test",)) is None


def test_company_user_cannot_create_admin_challenge(client, auth_headers):
    assert client.post("/api/admin/challenges", headers=auth_headers, json=CHALLENGE).status_code in (401, 403)


def test_developer_cannot_update_or_delete_admin_challenge(client):
    headers = _developer(client)
    dev = fetch_one("SELECT id FROM users WHERE email = ?", ("dev@test.com",))
    execute(
        """INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category)
           VALUES ('gc1', ?, 'Keep', 'keep', 'd', '# p', 'easy', 'backend')""",
        (dev["id"],),
    )
    assert client.put("/api/admin/challenges/gc1", headers=headers, json={"title": "Pwned"}).status_code in (401, 403)
    assert client.delete("/api/admin/challenges/gc1", headers=headers).status_code in (401, 403)
    row = fetch_one("SELECT title FROM challenges WHERE id = 'gc1'")
    assert row is not None and row["title"] == "Keep"
