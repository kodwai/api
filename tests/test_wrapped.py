from app.routers.developer_profiles import pick_favorite


def test_pick_favorite_most_frequent():
    rows = [{"agent_used": "cursor", "count": 2}, {"agent_used": "claude-code", "count": 5}]
    assert pick_favorite(rows, "agent_used") == "claude-code"


def test_pick_favorite_empty_or_null():
    assert pick_favorite([], "agent_used") is None
    assert pick_favorite([{"agent_used": None, "count": 9}], "agent_used") is None
