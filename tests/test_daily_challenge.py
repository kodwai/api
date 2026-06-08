from app.routers.challenges import daily_index


def test_daily_index_in_range():
    for d in ["2026-06-07", "2026-01-01", "2026-12-31"]:
        assert 0 <= daily_index(d, 15) < 15


def test_daily_index_stable_same_day():
    assert daily_index("2026-06-07", 15) == daily_index("2026-06-07", 15)


def test_daily_index_rotates_across_days():
    vals = {daily_index(f"2026-06-{day:02d}", 15) for day in range(1, 29)}
    assert len(vals) > 1


def test_daily_index_zero_count():
    assert daily_index("2026-06-07", 0) == 0


def test_daily_challenge_endpoint(client, auth_headers):
    resp = client.get("/api/challenges/daily", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "challenge" in body
    assert "completed_today" in body
    assert body["completed_today"] is False
    assert "date" in body
    assert "id" in body["challenge"]
