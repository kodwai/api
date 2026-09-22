"""Automation auth: require_scope (kdw_at_ tokens and superadmin JWTs), whoami, token CRUD."""
from __future__ import annotations

import secrets
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.automation_deps import require_scope
from app.core.database import execute, fetch_all, fetch_one
from app.core.security import create_access_token
from app.services.automation_tokens import hash_token, mint_token


def _user(email: str, *, superadmin: bool) -> str:
    org_id, uid = secrets.token_hex(16), secrets.token_hex(16)
    execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, "Org"))
    execute(
        """INSERT INTO users (id, email, password_hash, name, organization_id, user_type, email_verified, is_superadmin)
           VALUES (?, ?, 'x', 'U', ?, ?, 1, ?)""",
        (uid, email, org_id, "company" if superadmin else "developer", int(superadmin)),
    )
    return uid


@pytest.fixture
def superadmin_id() -> str:
    return _user("root@test.com", superadmin=True)


@pytest.fixture
def admin_headers(superadmin_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': superadmin_id, 'type': 'admin'})}"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# A throwaway app with one scoped route, so require_scope is tested independently of the
# routes later builders attach to it.
_scoped_app = FastAPI()


@_scoped_app.get("/scoped")
def _scoped(principal: Annotated[dict[str, Any], Depends(require_scope("lifecycle:run"))]) -> dict:
    return principal


@pytest.fixture
def scoped() -> TestClient:
    return TestClient(_scoped_app)


# ---------------------------------------------------------------------------
# require_scope
# ---------------------------------------------------------------------------

def test_valid_token_with_scope(scoped, superadmin_id):
    tok = mint_token("routine", ["lifecycle:run", "email:read"], superadmin_id)
    resp = scoped.get("/scoped", headers=_bearer(tok["token"]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == superadmin_id
    assert body["via"] == "token"
    assert body["token_id"] == tok["id"]
    assert body["scopes"] == ["email:read", "lifecycle:run"]
    assert fetch_one("SELECT last_used_at FROM automation_tokens WHERE id = ?", (tok["id"],))["last_used_at"]


def test_token_missing_scope_is_403(scoped, superadmin_id):
    tok = mint_token("reader", ["email:read"], superadmin_id)
    resp = scoped.get("/scoped", headers=_bearer(tok["token"]))
    assert resp.status_code == 403
    assert "lifecycle:run" in resp.json()["detail"]


def test_revoked_token_is_401(scoped, superadmin_id):
    tok = mint_token("routine", ["lifecycle:run"], superadmin_id)
    execute("UPDATE automation_tokens SET revoked_at = datetime('now') WHERE id = ?", (tok["id"],))
    assert scoped.get("/scoped", headers=_bearer(tok["token"])).status_code == 401


def test_expired_token_is_401(scoped, superadmin_id):
    tok = mint_token("routine", ["lifecycle:run"], superadmin_id)
    execute("UPDATE automation_tokens SET expires_at = '2020-01-01 00:00:00' WHERE id = ?", (tok["id"],))
    assert scoped.get("/scoped", headers=_bearer(tok["token"])).status_code == 401


def test_unknown_token_is_401(scoped):
    assert scoped.get("/scoped", headers=_bearer("kdw_at_" + "x" * 43)).status_code == 401


def test_token_dies_with_owner_superadmin_status(scoped, superadmin_id):
    tok = mint_token("routine", ["lifecycle:run"], superadmin_id)
    execute("UPDATE users SET is_superadmin = 0 WHERE id = ?", (superadmin_id,))
    assert scoped.get("/scoped", headers=_bearer(tok["token"])).status_code == 403


def test_superadmin_jwt_carries_all_scopes(scoped, admin_headers, superadmin_id):
    resp = scoped.get("/scoped", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["via"] == "superadmin"
    assert body["token_id"] is None
    assert body["id"] == superadmin_id
    assert "stats:read" in body["scopes"] and "blog:publish" in body["scopes"]


def test_developer_jwt_rejected(scoped):
    dev_id = _user("dev@test.com", superadmin=False)
    # A normal user JWT (no type=admin) must not pass.
    assert scoped.get("/scoped", headers=_bearer(create_access_token({"sub": dev_id}))).status_code == 401
    # Even a forged type=admin JWT for a non-superadmin is refused.
    forged = create_access_token({"sub": dev_id, "type": "admin"})
    assert scoped.get("/scoped", headers=_bearer(forged)).status_code == 403


def test_missing_header_is_401(scoped):
    resp = scoped.get("/scoped")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_require_scope_rejects_unknown_scope_at_definition():
    with pytest.raises(ValueError):
        require_scope("users:write")


# ---------------------------------------------------------------------------
# whoami
# ---------------------------------------------------------------------------

def test_whoami_with_token(client, superadmin_id):
    tok = mint_token("routine", ["stats:read"], superadmin_id)
    resp = client.get("/api/admin/automation/whoami", headers=_bearer(tok["token"]))
    assert resp.status_code == 200
    assert resp.json() == {"via": "token", "token_id": tok["id"], "scopes": ["stats:read"], "owner_user_id": superadmin_id}


def test_whoami_with_superadmin_jwt(client, admin_headers, superadmin_id):
    body = client.get("/api/admin/automation/whoami", headers=admin_headers).json()
    assert body["via"] == "superadmin" and body["owner_user_id"] == superadmin_id and len(body["scopes"]) == 7


def test_whoami_unauthenticated(client):
    assert client.get("/api/admin/automation/whoami").status_code == 401


# ---------------------------------------------------------------------------
# Token CRUD (superadmin JWT only)
# ---------------------------------------------------------------------------

def test_create_token_returns_plaintext_once(client, admin_headers, superadmin_id):
    resp = client.post("/api/admin/automation-tokens", headers=admin_headers,
                       json={"name": "daily routine", "scopes": ["stats:read", "lifecycle:run", "stats:read"]})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["token"].startswith("kdw_at_")
    assert body["token"].startswith(body["token_prefix"])
    assert body["scopes"] == ["lifecycle:run", "stats:read"]
    assert body["expires_at"]

    row = fetch_one("SELECT token_hash, owner_user_id, expires_at FROM automation_tokens WHERE id = ?", (body["id"],))
    assert row["token_hash"] == hash_token(body["token"])
    assert row["owner_user_id"] == superadmin_id
    # Default 90-day expiry.
    days = fetch_one("SELECT CAST(julianday(?) - julianday('now') + 0.5 AS INTEGER) AS d", (row["expires_at"],))["d"]
    assert days == 90

    audit = fetch_all("SELECT action, details FROM admin_audit_log WHERE entity_type = 'automation_token' AND entity_id = ?", (body["id"],))
    assert [a["action"] for a in audit] == ["create_automation_token"]
    assert body["token"] not in audit[0]["details"]

    listing = client.get("/api/admin/automation-tokens", headers=admin_headers).json()
    assert [t["id"] for t in listing["items"]] == [body["id"]]
    assert "token" not in listing["items"][0] and "token_hash" not in listing["items"][0]


def test_create_token_rejects_unknown_scope(client, admin_headers):
    resp = client.post("/api/admin/automation-tokens", headers=admin_headers,
                       json={"name": "bad", "scopes": ["lifecycle:run", "users:write"]})
    assert resp.status_code == 400
    assert "users:write" in resp.json()["detail"]
    assert fetch_one("SELECT COUNT(*) AS n FROM automation_tokens")["n"] == 0


def test_create_token_rejects_empty_scopes_and_bad_expiry(client, admin_headers):
    assert client.post("/api/admin/automation-tokens", headers=admin_headers,
                       json={"name": "x", "scopes": []}).status_code == 422
    assert client.post("/api/admin/automation-tokens", headers=admin_headers,
                       json={"name": "x", "scopes": ["stats:read"], "expires_days": 0}).status_code == 422


def test_automation_token_cannot_manage_tokens(client, superadmin_id):
    tok = mint_token("routine", ["lifecycle:run", "email:read", "feedback:read", "feedback:reply",
                                 "blog:write", "blog:publish", "stats:read"], superadmin_id)
    headers = _bearer(tok["token"])
    assert client.post("/api/admin/automation-tokens", headers=headers,
                       json={"name": "escalate", "scopes": ["stats:read"]}).status_code == 401
    assert client.get("/api/admin/automation-tokens", headers=headers).status_code == 401
    assert client.delete(f"/api/admin/automation-tokens/{tok['id']}", headers=headers).status_code == 401


def test_developer_cannot_manage_tokens(client):
    dev_id = _user("dev@test.com", superadmin=False)
    headers = _bearer(create_access_token({"sub": dev_id}))
    assert client.post("/api/admin/automation-tokens", headers=headers,
                       json={"name": "x", "scopes": ["stats:read"]}).status_code in (401, 403)


def test_revoke_token_is_idempotent(client, admin_headers, superadmin_id):
    tok = mint_token("routine", ["stats:read"], superadmin_id)
    first = client.delete(f"/api/admin/automation-tokens/{tok['id']}", headers=admin_headers)
    assert first.status_code == 200
    assert first.json()["revoked_at"]
    second = client.delete(f"/api/admin/automation-tokens/{tok['id']}", headers=admin_headers)
    assert second.status_code == 200
    assert second.json()["revoked_at"] == first.json()["revoked_at"]
    audit = fetch_all("SELECT action FROM admin_audit_log WHERE action = 'revoke_automation_token'")
    assert len(audit) == 1
    assert client.get("/api/admin/automation/whoami", headers=_bearer(tok["token"])).status_code == 401


def test_revoke_unknown_token_404(client, admin_headers):
    assert client.delete("/api/admin/automation-tokens/nope", headers=admin_headers).status_code == 404
