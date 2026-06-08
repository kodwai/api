from app.services.badge_engine import badge_progress

S = {"challenges_completed": 3, "streak_days": 5, "categories_count": 2, "agent_scores": {"claude-code": 4}}

def test_challenges():
    assert badge_progress({"type": "challenges_completed", "min": 10}, S) == {"progressable": True, "current": 3, "target": 10}
def test_streak():
    assert badge_progress({"type": "streak", "min": 7}, S)["current"] == 5
def test_categories():
    assert badge_progress({"type": "categories", "min": 3}, S)["target"] == 3
def test_agent_score():
    assert badge_progress({"type": "agent_score", "agent": "claude-code", "min_count": 5}, S) == {"progressable": True, "current": 4, "target": 5}
def test_non_countable_not_progressable():
    assert badge_progress({"type": "min_score", "min": 95}, S)["progressable"] is False
