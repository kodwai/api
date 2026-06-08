import secrets
from datetime import datetime, timezone

from app.core.database import execute
from app.core.security import hash_password
from app.routers.sprint import sprint_index, week_window
from app.routers.challenges import daily_index


def test_week_window_monday_boundary():
    wk, start, end = week_window(datetime(2026, 6, 3, 15, 30, tzinfo=timezone.utc))
    assert start == "2026-06-01 00:00:00"
    assert end == "2026-06-08 00:00:00"
    assert wk == "2026-W23"


def test_week_window_on_monday_is_inclusive_start():
    wk, start, end = week_window(datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc))
    assert start == "2026-06-01 00:00:00"
    assert end == "2026-06-08 00:00:00"


def test_week_window_on_sunday_late_still_same_week():
    wk, start, end = week_window(datetime(2026, 6, 7, 23, 59, 59, tzinfo=timezone.utc))
    assert start == "2026-06-01 00:00:00"
    assert end == "2026-06-08 00:00:00"


def test_sprint_index_deterministic_and_in_range():
    assert sprint_index("2026-W23", 5) == sprint_index("2026-W23", 5)
    assert 0 <= sprint_index("2026-W23", 5) < 5
    assert sprint_index("2026-W23", 0) == 0


def test_sprint_salt_differs_from_daily():
    keys = ["2026-W01", "2026-W10", "2026-W23", "2026-W44", "2025-W52"]
    same = sum(1 for k in keys if sprint_index(k, 7) == daily_index(k, 7))
    assert same < len(keys)


def _admin_headers(client):
    uid = secrets.token_hex(16)
    org_id = secrets.token_hex(16)
    password = "AdminPass2024!"
    execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, "Sprint Admin Org"))
    execute(
        """INSERT INTO users (id, email, password_hash, name, role, organization_id,
                              email_verified, is_superadmin)
           VALUES (?, ?, ?, ?, 'admin', ?, 1, 1)""",
        (uid, "sprint-admin@test.com", hash_password(password), "Sprint Admin", org_id),
    )
    resp = client.post("/api/admin/login", json={"email": "sprint-admin@test.com", "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_current_sprint_endpoint(client, auth_headers):
    admin_headers = _admin_headers(client)
    resp = client.post("/api/admin/challenges", headers=admin_headers, json={
        "title": "Sprint Test Challenge",
        "slug": "sprint-test-challenge",
        "description": "A challenge for sprint tests",
        "problem_statement_md": "# Build it",
        "difficulty": "easy",
        "category": "backend",
    })
    assert resp.status_code == 201, resp.text

    resp = client.get("/api/sprint/current", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("week_key", "starts_at", "ends_at", "challenge", "leaderboard", "me"):
        assert key in body
