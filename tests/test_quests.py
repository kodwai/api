from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.services.quests import _window, period_key, get_quest, load_quests

NOW = datetime(2026, 6, 10, 15, 0, 0, tzinfo=timezone.utc)  # Wednesday


def test_daily_window():
    pk, start, end = _window("daily", NOW)
    assert pk == "2026-06-10"
    assert start == "2026-06-10 00:00:00"
    assert end == "2026-06-11 00:00:00"


def test_weekly_window():
    pk, start, end = _window("weekly", NOW)
    assert pk == "2026-W24"
    assert start == "2026-06-08 00:00:00"   # Monday
    assert end == "2026-06-15 00:00:00"


def test_quest_registry():
    """DB-backed: migration 036 seeds the quests table (fresh_db fixture is autouse)."""
    assert len(load_quests()) == 4
    assert get_quest("daily_solve")["reward_xp"] == 50
    assert get_quest("nope") is None
    assert period_key(get_quest("daily_solve"), NOW) == "2026-06-10"


def test_list_quests_authed(client: TestClient, auth_headers: dict[str, str]):
    resp = client.get("/api/quests", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 4
    for item in data:
        for k in ("key", "scope", "target", "current", "completed", "claimed", "reward_xp"):
            assert k in item


def test_claim_incomplete_quest_returns_400(client: TestClient, auth_headers: dict[str, str]):
    # Fresh user with no submissions -> quest not complete.
    resp = client.post("/api/quests/daily_solve/claim", headers=auth_headers)
    assert resp.status_code == 400


def test_claim_unknown_quest_returns_404(client: TestClient, auth_headers: dict[str, str]):
    resp = client.post("/api/quests/bogus/claim", headers=auth_headers)
    assert resp.status_code == 404
