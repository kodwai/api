"""End-to-end test: POST /start → POST /submit produces a v2 score breakdown.

Threading strategy: we replace ``threading.Thread`` in the submissions router
with a ``FakeThread`` class whose ``start()`` only captures target/args without
launching a real thread.  This lets the HTTP handler complete normally (no
libsql re-entrancy issues), after which we call the scorer synchronously.

No real network, no real DB (in-memory via fresh_db fixture).
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
        # Intentionally a no-op — the test will call the target directly.
        pass


def _developer_headers(client) -> dict[str, str]:
    """Sign up a developer account, verify email in-DB, login, return auth headers.

    Developer accounts require ``user_type="developer"`` and a ``username``
    (no organization_name).  Email verification is bypassed by directly setting
    ``email_verified=1`` in the in-memory DB — identical to the pattern used by
    ``_create_verified_user`` in conftest.py for company users.
    """
    resp = client.post("/api/auth/signup", json={
        "email": "dev@test.com",
        "password": "testpass123",
        "name": "Dev User",
        "user_type": "developer",
        "username": "devuser",
    })
    assert resp.status_code == 201, f"signup failed: {resp.text}"

    # Manually verify email (no real email service in tests)
    user = fetch_one("SELECT id FROM users WHERE email='dev@test.com'")
    execute("UPDATE users SET email_verified=1 WHERE id=?", (user["id"],))

    resp = client.post("/api/auth/login", json={
        "email": "dev@test.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200, f"login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_submit_produces_v2_breakdown(client, monkeypatch):
    """Full path: start → submit → scoring runs after response → v2 breakdown in DB.

    The developer has no own key, so the submission rides the platform free tier:
    we enable it via the platform key and stub the LLM judge so scoring stays
    deterministic and offline.
    """
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test-platform")
    headers = _developer_headers(client)

    # Insert a public challenge (scoring_config='{}' → resolves to balanced profile)
    dev_user = fetch_one("SELECT id FROM users WHERE email='dev@test.com'")
    execute(
        "INSERT INTO challenges "
        "(id, created_by, title, slug, description, problem_statement_md, "
        "difficulty, category, time_limit_minutes, scoring_config, is_public) "
        "VALUES ('c1', ?, 'Test Challenge', 'test-challenge', 'desc', 'Build X', "
        "'easy', 'algo', 60, '{}', 1)",
        (dev_user["id"],),
    )

    # Start the challenge
    start_resp = client.post("/api/challenges/c1/start", headers=headers)
    assert start_resp.status_code == 201, f"start failed: {start_resp.text}"
    sub_id = start_resp.json()["submission_id"]

    # Replace threading.Thread in the submissions router with FakeThread so the
    # HTTP handler completes without launching a real thread (avoids libsql
    # re-entrancy issues while the connection is active inside the handler).
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
                    {"role": "user", "content": "No, that's wrong — handle empty input. Fix it."},
                    {"role": "assistant", "content": "Fixed. Now handles empty input."},
                ]},
                "time_taken_ms": 600000,
            },
        )
    assert resp.status_code == 200, f"submit failed: {resp.text}"

    # The submission should be reserved against the platform free tier.
    assert fetch_one("SELECT key_source FROM submissions WHERE id=?", (sub_id,))["key_source"] == "platform"

    # HTTP response has returned.  Now run the captured scorer synchronously with
    # the LLM judge stubbed out (deterministic, no network).
    assert len(fake_thread_instance) == 1, "expected exactly one background scoring thread"
    t = fake_thread_instance[0]
    with patch("app.services.scoring.llm.LLMJudge.judge", return_value={}), \
         patch("app.services.scoring.llm.LLMJudge.judge_rubric", return_value={}):
        t._target(*t._args)  # calls score_submission(sub_id)

    # Verify DB row has scoring_version=2 and the right axes
    row = fetch_one(
        "SELECT score, scoring_version, score_breakdown FROM submissions WHERE id=?",
        (sub_id,),
    )
    assert row is not None
    assert row["scoring_version"] == 2, f"expected scoring_version=2, got {row['scoring_version']}"

    bd = json.loads(row["score_breakdown"])
    axis_names = {a["name"] for a in bd["axes"]}
    assert axis_names == {"direction", "outcome", "lift"}, (
        f"unexpected axes: {axis_names}"
    )
