"""KOD-79 Phase 1, Task 2: the scoring engine records a `celebration` payload.

After a submission is scored, the engine should persist a JSON `celebration`
column describing what just happened (score, personal-best flag, newly-awarded
badges) so the results page can celebrate it once.

This mirrors the start → submit → score flow used by
``tests/scoring/test_submit_e2e.py`` (FakeThread captures the background scorer,
which we then run synchronously with the LLM judge stubbed for determinism).
"""
from __future__ import annotations

import json
from unittest.mock import patch

from app.core.database import execute, fetch_one


class _FakeThread:
    """Drop-in for ``threading.Thread`` that captures target/args instead of starting a thread."""

    def __init__(self, target=None, args=(), daemon=None, **kwargs):
        self._target = target
        self._args = args

    def start(self) -> None:
        # Intentionally a no-op — the test calls the target directly.
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


def test_scoring_records_celebration(client, monkeypatch):
    """start → submit → score persists a celebration payload with personal_best,
    score, and new_badges (including first-blood for the first completed challenge)."""
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

    fake_thread_instance: list[_FakeThread] = []

    class _CapturingFakeThread(_FakeThread):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            fake_thread_instance.append(self)

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

    assert len(fake_thread_instance) == 1, "expected exactly one background scoring thread"
    t = fake_thread_instance[0]
    with patch("app.services.scoring.llm.LLMJudge.judge", return_value={}), \
         patch("app.services.scoring.llm.LLMJudge.judge_rubric", return_value={}):
        t._target(*t._args)  # calls score_submission(sub_id)

    row = fetch_one("SELECT score, celebration FROM submissions WHERE id = ?", (sub_id,))
    assert row is not None
    assert row["celebration"] is not None, "celebration payload was not persisted"

    cel = json.loads(row["celebration"])
    assert cel["personal_best"] is True
    assert cel["score"] == row["score"]
    assert isinstance(cel["new_badges"], list)
    # First completed challenge → first-blood milestone badge.
    assert any(b["slug"] == "first-blood" for b in cel["new_badges"]), (
        f"expected first-blood badge, got {[b['slug'] for b in cel['new_badges']]}"
    )
