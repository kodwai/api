"""API key endpoint tests."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.database import fetch_one


# ── List Keys ───────────────────────────────────────────────


def test_list_keys_empty(client: TestClient, auth_headers):
    resp = client.get("/api/api-keys", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_keys_unauthenticated(client: TestClient):
    resp = client.get("/api/api-keys")
    assert resp.status_code == 401


# ── Add Key ─────────────────────────────────────────────────


@patch("app.routers.api_keys._validate_anthropic_key", return_value=True)
def test_add_key_success(mock_validate, client: TestClient, auth_headers):
    resp = client.post("/api/api-keys", headers=auth_headers, json={
        "key": "sk-ant-api03-realkey1234567890",
        "label": "Production Key",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["label"] == "Production Key"
    assert data["key_last4"] == "7890"
    assert data["is_active"] is True
    assert "id" in data


@patch("app.routers.api_keys._validate_anthropic_key", return_value=True)
def test_add_key_stored_encrypted(mock_validate, client: TestClient, auth_headers):
    client.post("/api/api-keys", headers=auth_headers, json={
        "key": "sk-ant-api03-mysecretkey9999",
        "label": "Test",
    })
    row = fetch_one("SELECT encrypted_key, key_iv, key_last4 FROM api_keys LIMIT 1")
    assert row is not None
    # Encrypted key should NOT be the original plaintext
    assert row["encrypted_key"] != "sk-ant-api03-mysecretkey9999"
    assert row["key_iv"] is not None
    assert row["key_last4"] == "9999"


@patch("app.routers.api_keys._validate_anthropic_key", return_value=False)
def test_add_invalid_key_rejected(mock_validate, client: TestClient, auth_headers):
    resp = client.post("/api/api-keys", headers=auth_headers, json={
        "key": "sk-ant-fake-bad-key-000",
        "label": "Bad Key",
    })
    assert resp.status_code == 400
    assert "Invalid" in resp.json()["detail"]


def test_add_key_too_short(client: TestClient, auth_headers):
    resp = client.post("/api/api-keys", headers=auth_headers, json={
        "key": "short",
        "label": "Bad",
    })
    assert resp.status_code == 422


# ── Delete Key ──────────────────────────────────────────────


@patch("app.routers.api_keys._validate_anthropic_key", return_value=True)
def test_delete_key(mock_validate, client: TestClient, auth_headers):
    resp = client.post("/api/api-keys", headers=auth_headers, json={
        "key": "sk-ant-api03-todelete1234567",
        "label": "Delete Me",
    })
    key_id = resp.json()["id"]

    resp = client.delete(f"/api/api-keys/{key_id}", headers=auth_headers)
    assert resp.status_code == 204

    resp = client.get("/api/api-keys", headers=auth_headers)
    assert len(resp.json()) == 0


def test_delete_nonexistent_key(client: TestClient, auth_headers):
    resp = client.delete("/api/api-keys/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


# ── Cross-Org Isolation ─────────────────────────────────────


@patch("app.routers.api_keys._validate_anthropic_key", return_value=True)
def test_cannot_see_other_org_keys(mock_validate, client: TestClient, auth_headers, second_user_headers):
    client.post("/api/api-keys", headers=auth_headers, json={
        "key": "sk-ant-api03-orgonekey12345",
        "label": "Org1 Key",
    })
    client.post("/api/api-keys", headers=second_user_headers, json={
        "key": "sk-ant-api03-orgtwokey67890",
        "label": "Org2 Key",
    })

    resp1 = client.get("/api/api-keys", headers=auth_headers)
    resp2 = client.get("/api/api-keys", headers=second_user_headers)

    assert len(resp1.json()) == 1
    assert resp1.json()[0]["label"] == "Org1 Key"
    assert len(resp2.json()) == 1
    assert resp2.json()[0]["label"] == "Org2 Key"


@patch("app.routers.api_keys._validate_anthropic_key", return_value=True)
def test_cannot_delete_other_org_key(mock_validate, client: TestClient, auth_headers, second_user_headers):
    resp = client.post("/api/api-keys", headers=auth_headers, json={
        "key": "sk-ant-api03-cannotdelete123",
        "label": "Protected",
    })
    key_id = resp.json()["id"]

    resp = client.delete(f"/api/api-keys/{key_id}", headers=second_user_headers)
    assert resp.status_code == 404
