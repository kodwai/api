"""Free-submission entitlement: /auth/me fields + challenge start/submit gating.

A developer gets FREE_SUBMISSION_LIMIT submissions scored on the platform key,
then must connect their own. The platform key is enabled per-test via monkeypatch
(conftest leaves PLATFORM_ANTHROPIC_API_KEY empty → free tier off by default).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import execute, fetch_one


class _FakeThread:
    """Captures the scoring target instead of running it (keeps tests offline)."""

    def __init__(self, target=None, args=(), daemon=None, **kwargs):
        self._target = target
        self._args = args

    def start(self) -> None:  # no-op
        pass


def _developer(client: TestClient, email: str = "dev@test.com", username: str = "devuser") -> tuple[dict, str]:
    """Sign up + verify + login a developer. Returns (auth_headers, user_id)."""
    resp = client.post("/api/auth/signup", json={
        "email": email, "password": "testpass123", "name": "Dev", "user_type": "developer", "username": username,
    })
    assert resp.status_code == 201, resp.text
    user = fetch_one("SELECT id FROM users WHERE email=?", (email,))
    execute("UPDATE users SET email_verified=1 WHERE id=?", (user["id"],))
    resp = client.post("/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user["id"]


def _make_challenge(created_by: str, cid: str = "c1", slug: str = "c1") -> str:
    execute(
        "INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, "
        "difficulty, category, time_limit_minutes, scoring_config, is_public) "
        "VALUES (?, ?, 'T', ?, 'd', 'Build X', 'easy', 'algo', 60, '{}', 1)",
        (cid, created_by, slug),
    )
    return cid


def _consume_free(user_id: str, n: int) -> None:
    """Simulate n spent free credits (monotonic counter on the developer profile)."""
    execute("UPDATE developer_profiles SET free_submissions_used = ? WHERE user_id = ?", (n, user_id))


# ── /auth/me entitlement ─────────────────────────────────────────────


def test_me_free_tier_on(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, _ = _developer(client)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["free_submissions_limit"] == 3
    assert me["free_submissions_remaining"] == 3
    assert me["free_submissions_used"] == 0
    assert me["can_submit"] is True
    assert me["has_claude_api_key"] is False


def test_me_free_tier_off_no_key(client):
    # PLATFORM_ANTHROPIC_API_KEY unset (conftest default) → no free tier.
    headers, _ = _developer(client)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["free_submissions_limit"] == 0
    assert me["free_submissions_remaining"] == 0
    assert me["can_submit"] is False


def test_me_remaining_decrements_with_usage(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _consume_free(user_id, 2)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["free_submissions_used"] == 2
    assert me["free_submissions_remaining"] == 1
    assert me["can_submit"] is True


def test_me_exhausted_blocks(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _consume_free(user_id, 3)
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["free_submissions_remaining"] == 0
    assert me["can_submit"] is False


def test_me_own_key_unlimited_even_without_platform(client):
    # No platform key, but an own key → unlimited.
    headers, user_id = _developer(client)
    execute("INSERT INTO api_keys (id, user_id, encrypted_key, key_iv, key_last4, is_active, label) "
            "VALUES ('k1', ?, 'enc', 'iv', 'last', 1, 'L')", (user_id,))
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["has_claude_api_key"] is True
    assert me["can_submit"] is True


# ── start gating ─────────────────────────────────────────────────────


def test_start_blocked_without_entitlement(client):
    headers, user_id = _developer(client)
    _make_challenge(user_id)
    resp = client.post("/api/challenges/c1/start", headers=headers)
    assert resp.status_code == 402


def test_start_allowed_on_free_tier(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _make_challenge(user_id)
    resp = client.post("/api/challenges/c1/start", headers=headers)
    assert resp.status_code == 201


def test_start_blocked_when_free_exhausted(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _make_challenge(user_id)
    _consume_free(user_id, 3)
    resp = client.post("/api/challenges/c1/start", headers=headers)
    assert resp.status_code == 402


# ── submit reserves the right key source ─────────────────────────────


def test_submit_reserves_platform_credit(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("app.routers.submissions.threading.Thread", _FakeThread)
    headers, user_id = _developer(client)
    _make_challenge(user_id)
    sub_id = client.post("/api/challenges/c1/start", headers=headers).json()["submission_id"]
    resp = client.post(f"/api/submissions/{sub_id}/submit", headers=headers,
                        json={"code_snapshot": [{"path": "a.py", "content": "x = 1"}], "time_taken_ms": 1000})
    assert resp.status_code == 200, resp.text
    assert fetch_one("SELECT key_source FROM submissions WHERE id=?", (sub_id,))["key_source"] == "platform"
    # The free credit is spent permanently on the profile counter.
    assert fetch_one("SELECT free_submissions_used FROM developer_profiles WHERE user_id=?", (user_id,))["free_submissions_used"] == 1


def test_submit_uses_own_key_source(client, monkeypatch):
    monkeypatch.setattr("app.routers.submissions.threading.Thread", _FakeThread)
    headers, user_id = _developer(client)
    execute("INSERT INTO api_keys (id, user_id, encrypted_key, key_iv, key_last4, is_active, label) "
            "VALUES ('k1', ?, 'enc', 'iv', 'last', 1, 'L')", (user_id,))
    _make_challenge(user_id)
    sub_id = client.post("/api/challenges/c1/start", headers=headers).json()["submission_id"]
    resp = client.post(f"/api/submissions/{sub_id}/submit", headers=headers,
                        json={"code_snapshot": [{"path": "a.py", "content": "x = 1"}], "time_taken_ms": 1000})
    assert resp.status_code == 200, resp.text
    assert fetch_one("SELECT key_source FROM submissions WHERE id=?", (sub_id,))["key_source"] == "user"


def test_submit_blocked_when_exhausted_midflight(client, monkeypatch):
    # Free tier ON, but all 3 credits were spent before this in_progress one is submitted.
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _make_challenge(user_id)
    _consume_free(user_id, 3)
    execute("INSERT INTO submissions (id, challenge_id, user_id, status) VALUES ('s_open', 'c1', ?, 'in_progress')",
            (user_id,))
    resp = client.post("/api/submissions/s_open/submit", headers=headers,
                        json={"code_snapshot": [{"path": "a.py", "content": "x = 1"}], "time_taken_ms": 1000})
    assert resp.status_code == 402


def test_submit_blocked_when_free_tier_off(client):
    # Platform key unset and no own key → cannot submit at all.
    headers, user_id = _developer(client)
    _make_challenge(user_id)
    execute("INSERT INTO submissions (id, challenge_id, user_id, status) VALUES ('s_open', 'c1', ?, 'in_progress')",
            (user_id,))
    resp = client.post("/api/submissions/s_open/submit", headers=headers,
                        json={"code_snapshot": [{"path": "a.py", "content": "x = 1"}], "time_taken_ms": 1000})
    assert resp.status_code == 402
