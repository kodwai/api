"""One-challenge-at-a-time enforcement + stop/delete submission with cleanup."""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app.core.database import execute, fetch_one


def _developer(client: TestClient, email: str = "dev@test.com", username: str = "devuser") -> tuple[dict, str]:
    resp = client.post("/api/auth/signup", json={
        "email": email, "password": "testpass123", "name": "Dev", "user_type": "developer", "username": username,
    })
    assert resp.status_code == 201, resp.text
    user = fetch_one("SELECT id FROM users WHERE email=?", (email,))
    execute("UPDATE users SET email_verified=1 WHERE id=?", (user["id"],))
    resp = client.post("/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user["id"]


def _make_challenge(created_by: str, cid: str = "c1", slug: str = "c1", difficulty: str = "easy") -> str:
    execute(
        "INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, "
        "difficulty, category, time_limit_minutes, scoring_config, is_public) "
        "VALUES (?, ?, 'T', ?, 'd', 'Build X', ?, 'algo', 60, '{}', 1)",
        (cid, created_by, slug, difficulty),
    )
    return cid


def _seed_scored(user_id: str, challenge_id: str, score: float, *, key_source: str = "user",
                 eligible: int = 1, sub_id: str | None = None) -> str:
    sub_id = sub_id or secrets.token_hex(8)
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id, status, score, leaderboard_eligible, "
        "agent_used, time_taken_ms, submitted_at, key_source) "
        "VALUES (?, ?, ?, 'scored', ?, ?, 'claude-code', 600000, datetime('now'), ?)",
        (sub_id, challenge_id, user_id, score, eligible, key_source),
    )
    return sub_id


def _seed_leaderboard(user_id: str, challenge_id: str, submission_id: str, score: float) -> None:
    execute(
        "INSERT INTO leaderboard_entries (id, user_id, challenge_id, submission_id, score, submitted_at) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (secrets.token_hex(8), user_id, challenge_id, submission_id, score),
    )


# ── one challenge at a time ──────────────────────────────────────────


def test_second_start_blocked(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    _make_challenge(user_id, "c2", "c2")
    assert client.post("/api/challenges/c1/start", headers=headers).status_code == 201
    resp = client.post("/api/challenges/c2/start", headers=headers)
    assert resp.status_code == 409


def test_stopping_active_frees_the_slot(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    _make_challenge(user_id, "c2", "c2")
    sub_id = client.post("/api/challenges/c1/start", headers=headers).json()["submission_id"]
    assert client.post("/api/challenges/c2/start", headers=headers).status_code == 409
    # Stop the active one, then a new start succeeds.
    assert client.delete(f"/api/submissions/{sub_id}", headers=headers).status_code == 204
    assert client.post("/api/challenges/c2/start", headers=headers).status_code == 201


def test_one_active_enforced_at_db_level(client):
    # The partial unique index is the authoritative guard against a start-start race.
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    execute("INSERT INTO submissions (id, challenge_id, user_id, status) VALUES ('a', 'c1', ?, 'in_progress')", (user_id,))
    with pytest.raises(Exception):
        execute("INSERT INTO submissions (id, challenge_id, user_id, status) VALUES ('b', 'c1', ?, 'in_progress')", (user_id,))


def test_active_endpoint(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    assert client.get("/api/submissions/active", headers=headers).json() is None
    sub_id = client.post("/api/challenges/c1/start", headers=headers).json()["submission_id"]
    active = client.get("/api/submissions/active", headers=headers).json()
    assert active is not None and active["id"] == sub_id and active["status"] == "in_progress"


# ── delete / stop ────────────────────────────────────────────────────


def test_stop_in_progress(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    sub_id = client.post("/api/challenges/c1/start", headers=headers).json()["submission_id"]
    assert client.delete(f"/api/submissions/{sub_id}", headers=headers).status_code == 204
    assert fetch_one("SELECT id FROM submissions WHERE id=?", (sub_id,)) is None


def test_delete_rebuilds_leaderboard_to_next_best(client):
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    hi = _seed_scored(user_id, "c1", 90)
    lo = _seed_scored(user_id, "c1", 70)
    _seed_leaderboard(user_id, "c1", hi, 90)
    # Delete the leaderboard-leading submission.
    assert client.delete(f"/api/submissions/{hi}", headers=headers).status_code == 204
    entry = fetch_one("SELECT submission_id, score FROM leaderboard_entries WHERE user_id=? AND challenge_id='c1'", (user_id,))
    assert entry is not None and entry["submission_id"] == lo and entry["score"] == 70


def test_delete_last_scored_removes_leaderboard_entry(client):
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    only = _seed_scored(user_id, "c1", 80)
    _seed_leaderboard(user_id, "c1", only, 80)
    assert client.delete(f"/api/submissions/{only}", headers=headers).status_code == 204
    assert fetch_one("SELECT id FROM leaderboard_entries WHERE user_id=? AND challenge_id='c1'", (user_id,)) is None
    prof = fetch_one("SELECT total_score, challenges_completed FROM developer_profiles WHERE user_id=?", (user_id,))
    assert prof["total_score"] == 0 and prof["challenges_completed"] == 0


def test_delete_recomputes_challenge_stats(client):
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    a = _seed_scored(user_id, "c1", 90)
    _seed_scored(user_id, "c1", 60)
    execute("UPDATE challenges SET submission_count=2, avg_score=75 WHERE id='c1'")
    assert client.delete(f"/api/submissions/{a}", headers=headers).status_code == 204
    ch = fetch_one("SELECT submission_count, avg_score FROM challenges WHERE id='c1'")
    assert ch["submission_count"] == 1 and ch["avg_score"] == 60


def test_delete_does_not_refund_free_credit(client, monkeypatch):
    # The whole point of the monotonic counter: deleting a platform submission must NOT refund.
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    execute("UPDATE developer_profiles SET free_submissions_used = 3 WHERE user_id = ?", (user_id,))
    sub = _seed_scored(user_id, "c1", 80, key_source="platform")
    assert client.delete(f"/api/submissions/{sub}", headers=headers).status_code == 204
    used = fetch_one("SELECT free_submissions_used FROM developer_profiles WHERE user_id=?", (user_id,))["free_submissions_used"]
    assert used == 3  # unchanged — no refund
    assert client.get("/api/auth/me", headers=headers).json()["free_submissions_remaining"] == 0


def test_cannot_delete_while_scoring(client):
    headers, user_id = _developer(client)
    _make_challenge(user_id, "c1", "c1")
    execute("INSERT INTO submissions (id, challenge_id, user_id, status) VALUES ('s1', 'c1', ?, 'scoring')", (user_id,))
    assert client.delete("/api/submissions/s1", headers=headers).status_code == 409


def test_cannot_delete_other_users_submission(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    a_headers, a_id = _developer(client, "a@test.com", "auser")
    b_headers, b_id = _developer(client, "b@test.com", "buser")
    _make_challenge(a_id, "c1", "c1")
    a_sub = client.post("/api/challenges/c1/start", headers=a_headers).json()["submission_id"]
    # B tries to delete A's submission.
    assert client.delete(f"/api/submissions/{a_sub}", headers=b_headers).status_code == 404
    assert fetch_one("SELECT id FROM submissions WHERE id=?", (a_sub,)) is not None
