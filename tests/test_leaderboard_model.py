"""Leaderboard model dimension (KOD-63 Task 5).

Verifies the /models filter listing, the model display reverse-lookup, and that
the global leaderboard's ?model= filter narrows to a single model's developers.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import execute


def _user(uid: str, name: str, username: str) -> None:
    execute(
        "INSERT INTO users (id, email, name, username, password_hash, email_verified) "
        "VALUES (?, ?, ?, ?, 'x', 1)",
        (uid, f"{username}@test.com", name, username),
    )
    execute("INSERT INTO developer_profiles (id, user_id) VALUES (?, ?)", (f"dp_{uid}", uid))


def _challenge(cid: str = "c1", slug: str = "c1", created_by: str = "u1") -> None:
    execute(
        "INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, "
        "difficulty, category, time_limit_minutes, scoring_config, is_public) "
        "VALUES (?, ?, 'T', ?, 'd', 'Build X', 'easy', 'algo', 60, '{}', 1)",
        (cid, created_by, slug),
    )


def _scored_submission(sid: str, user_id: str, challenge_id: str, score: float, model: str) -> None:
    """A scored, leaderboard-eligible submission carrying a model slug."""
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id, status, score, agent_used, model, "
        "leaderboard_eligible, time_taken_ms) "
        "VALUES (?, ?, ?, 'scored', ?, 'claude-code', ?, 1, 1000)",
        (sid, challenge_id, user_id, score, model),
    )
    # Mirror what the scoring engine writes for per-challenge boards.
    execute(
        "INSERT INTO leaderboard_entries (id, user_id, challenge_id, submission_id, score, agent_used, model, submitted_at) "
        "VALUES (?, ?, ?, ?, ?, 'claude-code', ?, datetime('now'))",
        (f"le_{sid}", user_id, challenge_id, sid, score, model),
    )


def _seed() -> None:
    _user("u1", "Alice", "alice")
    _user("u2", "Bob", "bob")
    _challenge(created_by="u1")
    _scored_submission("s1", "u1", "c1", 90.0, "claude-opus-4-8")
    _scored_submission("s2", "u2", "c1", 80.0, "gpt-5.5")


def test_leaderboard_models_lists_distinct_slugs_with_display(client: TestClient):
    _seed()
    resp = client.get("/api/leaderboard/models")
    assert resp.status_code == 200, resp.text
    models = resp.json()
    by_slug = {m["slug"]: m["display"] for m in models}
    assert by_slug["claude-opus-4-8"] == "Opus 4.8"
    assert by_slug["gpt-5.5"] == "GPT-5.5"


def test_global_leaderboard_filters_by_model(client: TestClient):
    _seed()
    resp = client.get("/api/leaderboard", params={"model": "gpt-5.5"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["entries"]) == 1
    assert body["entries"][0]["username"] == "bob"
