"""KOD-79: per-category and per-model mastery ratings (ELO).

After a submission is scored, the engine upserts a per-category and per-model
``user_skill_ratings`` row via the same ELO ``update_rating`` used for the
Direction Rating. The ``GET /api/developers/me/skills`` endpoint exposes them.

The scoring flow mirrors ``tests/test_celebration.py`` (FakeThread captures the
background scorer, run synchronously with the LLM judge stubbed for determinism).
"""
from __future__ import annotations

from unittest.mock import patch

from app.core.database import execute, fetch_all, fetch_one


class _FakeThread:
    """Drop-in for ``threading.Thread`` that captures target/args instead of starting a thread."""

    def __init__(self, target=None, args=(), daemon=None, **kwargs):
        self._target = target
        self._args = args

    def start(self) -> None:
        pass


def _developer_headers(client) -> dict[str, str]:
    resp = client.post("/api/auth/signup", json={
        "email": "dev@test.com",
        "password": "testpass123",
        "name": "Dev User",
        "user_type": "developer",
        "username": "devuser",
    })
    assert resp.status_code == 201, f"signup failed: {resp.text}"

    user = fetch_one("SELECT id FROM users WHERE email='dev@test.com'")
    execute("UPDATE users SET email_verified=1 WHERE id=?", (user["id"],))

    resp = client.post("/api/auth/login", json={
        "email": "dev@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_scoring_upserts_skill_rating(client, monkeypatch):
    """start → submit → score upserts a category skill rating for the scored challenge."""
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test-platform")
    headers = _developer_headers(client)

    dev_user = fetch_one("SELECT id FROM users WHERE email='dev@test.com'")
    execute(
        "INSERT INTO challenges "
        "(id, created_by, title, slug, description, problem_statement_md, "
        "difficulty, category, time_limit_minutes, scoring_config, is_public) "
        "VALUES ('c1', ?, 'Test Challenge', 'test-challenge', 'desc', 'Build X', "
        "'easy', 'algo', 60, '{}', 1)",
        (dev_user["id"],),
    )

    start_resp = client.post("/api/challenges/c1/start", headers=headers)
    assert start_resp.status_code == 201, f"start failed: {start_resp.text}"
    sub_id = start_resp.json()["submission_id"]

    captured: list[_FakeThread] = []

    class _CapturingFakeThread(_FakeThread):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured.append(self)

    with patch("app.routers.submissions.threading.Thread", _CapturingFakeThread):
        resp = client.post(
            f"/api/submissions/{sub_id}/submit",
            headers=headers,
            json={
                "code_snapshot": [{"path": "a.py", "content": "def f():\n    return 1\n"}],
                "test_results": {"passed": 5, "total": 10, "output": ""},
                "agent_used": "claude-code",
                "agent_trace": {"turns": [
                    {"role": "user", "content": "Build X carefully with edge cases."},
                    {"role": "assistant", "content": "Here is the implementation."},
                ]},
                "time_taken_ms": 600000,
            },
        )
    assert resp.status_code == 200, f"submit failed: {resp.text}"

    assert len(captured) == 1, "expected exactly one background scoring thread"
    t = captured[0]
    with patch("app.services.scoring.llm.LLMJudge.judge", return_value={}), \
         patch("app.services.scoring.llm.LLMJudge.judge_rubric", return_value={}):
        t._target(*t._args)  # calls score_submission(sub_id)

    rows = fetch_all(
        "SELECT dimension, key, rating FROM user_skill_ratings WHERE user_id = ? AND dimension = 'category'",
        (dev_user["id"],),
    )
    assert len(rows) == 1, f"expected one category skill rating, got {rows}"
    assert rows[0]["key"] == "algo"
    assert rows[0]["rating"] != 1000, "rating should have moved from the 1000 default after scoring"


def test_my_skills_endpoint(client):
    """GET /api/developers/me/skills returns 200 with category and model lists."""
    headers = _developer_headers(client)
    dev_user = fetch_one("SELECT id FROM users WHERE email='dev@test.com'")

    execute(
        "INSERT INTO user_skill_ratings (user_id, dimension, key, rating) VALUES (?, 'category', 'algo', 1120)",
        (dev_user["id"],),
    )
    execute(
        "INSERT INTO user_skill_ratings (user_id, dimension, key, rating) VALUES (?, 'model', 'claude-opus', 980)",
        (dev_user["id"],),
    )

    resp = client.get("/api/developers/me/skills", headers=headers)
    assert resp.status_code == 200, f"skills endpoint failed: {resp.text}"
    body = resp.json()
    assert "category" in body and "model" in body
    assert body["category"] == [{"key": "algo", "rating": 1120}]
    assert body["model"] == [{"key": "claude-opus", "rating": 980}]
