import secrets
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.core.database import execute
from app.core.security import hash_password
from app.services.feature_flags import is_flag_active

NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


def test_missing_flag_inactive():
    assert is_flag_active(None, NOW) is False


def test_disabled_inactive():
    assert is_flag_active({"enabled": 0}, NOW) is False


def test_enabled_no_window_active():
    assert is_flag_active({"enabled": 1}, NOW) is True


def test_before_window_inactive():
    assert is_flag_active({"enabled": 1, "starts_at": "2026-12-01 00:00:00"}, NOW) is False


def test_after_window_inactive():
    assert is_flag_active({"enabled": 1, "ends_at": "2026-01-01 00:00:00"}, NOW) is False


def test_within_window_active():
    assert is_flag_active({"enabled": 1, "starts_at": "2026-06-01 00:00:00", "ends_at": "2026-06-30 00:00:00"}, NOW) is True


# ---------------------------------------------------------------------------
# Endpoint smoke tests
# ---------------------------------------------------------------------------

def _make_admin_headers(client: TestClient) -> dict[str, str]:
    """Create a superadmin user in the DB and return admin JWT headers."""
    uid = secrets.token_hex(16)
    password = "AdminPass2024!"
    org_id = secrets.token_hex(16)

    execute(
        "INSERT INTO organizations (id, name) VALUES (?, ?)",
        (org_id, "Admin Org"),
    )
    execute(
        """INSERT INTO users (id, email, password_hash, name, role, organization_id,
                              email_verified, is_superadmin)
           VALUES (?, ?, ?, ?, 'admin', ?, 1, 1)""",
        (uid, "superadmin@test.com", hash_password(password), "Super Admin", org_id),
    )

    resp = client.post("/api/admin/login", json={
        "email": "superadmin@test.com",
        "password": password,
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _find_flag(items: list[dict], key: str) -> dict:
    for item in items:
        if item["key"] == key:
            return item
    raise AssertionError(f"flag {key!r} not in {items!r}")


def test_public_list_feature_flags(client):
    resp = client.get("/api/feature-flags")
    assert resp.status_code == 200, resp.text
    flag = _find_flag(resp.json(), "weekly_sprint")
    assert flag["active"] is True


def test_admin_disable_flag_marks_inactive(client):
    admin_headers = _make_admin_headers(client)
    resp = client.put(
        "/api/admin/feature-flags/weekly_sprint",
        headers=admin_headers,
        json={"enabled": False},
    )
    assert resp.status_code == 200, resp.text

    listing = client.get("/api/feature-flags")
    assert listing.status_code == 200
    flag = _find_flag(listing.json(), "weekly_sprint")
    assert flag["active"] is False


def test_disabled_flag_gates_sprint(client, auth_headers):
    execute("UPDATE feature_flags SET enabled = 0 WHERE key = ?", ("weekly_sprint",))
    resp = client.get("/api/sprint/current", headers=auth_headers)
    assert resp.status_code == 404, resp.text
