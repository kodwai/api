import secrets

from fastapi.testclient import TestClient

from app.core.database import execute
from app.core.security import hash_password


def _make_admin_headers(client: TestClient) -> dict[str, str]:
    """Create a superadmin user in the DB and return admin JWT headers."""
    uid = secrets.token_hex(16)
    password = "AdminPass2024!"
    org_id = secrets.token_hex(16)
    email = f"superadmin_{uid}@test.com"

    execute(
        "INSERT INTO organizations (id, name) VALUES (?, ?)",
        (org_id, "Admin Org"),
    )
    execute(
        """INSERT INTO users (id, email, password_hash, name, role, organization_id,
                              email_verified, is_superadmin)
           VALUES (?, ?, ?, ?, 'admin', ?, 1, 1)""",
        (uid, email, hash_password(password), "Super Admin", org_id),
    )

    resp = client.post("/api/admin/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _find(items: list[dict], key: str) -> dict:
    for item in items:
        if item["key"] == key:
            return item
    raise AssertionError(f"{key!r} not in {items!r}")


# ---- Tiers ----

def test_list_tiers(client):
    headers = _make_admin_headers(client)
    resp = client.get("/api/admin/tiers", headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 7
    _find(rows, "gold")


def test_update_tier_roundtrip(client):
    headers = _make_admin_headers(client)
    resp = client.put(
        "/api/admin/tiers/gold",
        headers=headers,
        json={"min_rating": 1175, "color": "#ffaa00"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["min_rating"] == 1175
    assert body["color"] == "#ffaa00"

    listing = client.get("/api/admin/tiers", headers=headers)
    gold = _find(listing.json(), "gold")
    assert gold["min_rating"] == 1175
    assert gold["color"] == "#ffaa00"


def test_update_unknown_tier_404(client):
    headers = _make_admin_headers(client)
    resp = client.put("/api/admin/tiers/nope", headers=headers, json={"min_rating": 1})
    assert resp.status_code == 404, resp.text


# ---- Quests ----

def test_list_quests(client):
    headers = _make_admin_headers(client)
    resp = client.get("/api/admin/quests", headers=headers)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 4


def test_update_quest_roundtrip(client):
    headers = _make_admin_headers(client)
    resp = client.put(
        "/api/admin/quests/daily_solve",
        headers=headers,
        json={"reward_xp": 60},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["reward_xp"] == 60

    listing = client.get("/api/admin/quests", headers=headers)
    assert _find(listing.json(), "daily_solve")["reward_xp"] == 60


def test_update_quest_bad_scope_400(client):
    headers = _make_admin_headers(client)
    resp = client.put(
        "/api/admin/quests/daily_solve",
        headers=headers,
        json={"scope": "bogus"},
    )
    assert resp.status_code == 400, resp.text


def test_update_unknown_quest_404(client):
    headers = _make_admin_headers(client)
    resp = client.put("/api/admin/quests/nope", headers=headers, json={"reward_xp": 1})
    assert resp.status_code == 404, resp.text


# ---- Auth ----

def test_tiers_requires_admin(client):
    resp = client.get("/api/admin/tiers")
    assert resp.status_code in (401, 403), resp.text


def test_quests_requires_admin(client, auth_headers):
    resp = client.get("/api/admin/quests", headers=auth_headers)
    assert resp.status_code in (401, 403), resp.text
