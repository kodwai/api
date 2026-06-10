from __future__ import annotations
from datetime import datetime, timedelta, timezone
from app.core.database import fetch_one

QUESTS = [
    {"key": "daily_solve",       "scope": "daily",  "title": "Daily solve",   "description": "Score a challenge today",         "target": 1, "reward_xp": 50,  "metric": "solved"},
    {"key": "daily_high",        "scope": "daily",  "title": "Sharp shooter", "description": "Score 80+ on a challenge today",  "target": 1, "reward_xp": 75,  "metric": "high80"},
    {"key": "weekly_three",      "scope": "weekly", "title": "Consistent",    "description": "Solve 3 challenges this week",    "target": 3, "reward_xp": 150, "metric": "solved"},
    {"key": "weekly_categories", "scope": "weekly", "title": "Explorer",      "description": "Solve in 2 categories this week", "target": 2, "reward_xp": 150, "metric": "categories"},
]
_BY_KEY = {q["key"]: q for q in QUESTS}

def _window(scope: str, now: datetime) -> tuple[str, str, str]:
    """(period_key, start, end) canonical 'YYYY-MM-DD HH:MM:SS' UTC for the quest scope."""
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%d %H:%M:%S"
    if scope == "weekly":
        monday = midnight - timedelta(days=now.weekday())
        return now.strftime("%G-W%V"), monday.strftime(fmt), (monday + timedelta(days=7)).strftime(fmt)
    return now.strftime("%Y-%m-%d"), midnight.strftime(fmt), (midnight + timedelta(days=1)).strftime(fmt)

def quest_progress(user_id: str, quest: dict, now: datetime) -> int:
    _, start, end = _window(quest["scope"], now)
    metric = quest["metric"]
    if metric == "categories":
        row = fetch_one(
            """SELECT COUNT(DISTINCT c.category) AS n FROM submissions s JOIN challenges c ON c.id=s.challenge_id
               WHERE s.user_id=? AND s.status='scored' AND datetime(s.scored_at)>=datetime(?) AND datetime(s.scored_at)<datetime(?)""",
            (user_id, start, end))
    elif metric == "high80":
        row = fetch_one(
            """SELECT COUNT(*) AS n FROM submissions s
               WHERE s.user_id=? AND s.status='scored' AND s.score>=80 AND datetime(s.scored_at)>=datetime(?) AND datetime(s.scored_at)<datetime(?)""",
            (user_id, start, end))
    else:  # solved = distinct challenges scored in window
        row = fetch_one(
            """SELECT COUNT(DISTINCT s.challenge_id) AS n FROM submissions s
               WHERE s.user_id=? AND s.status='scored' AND datetime(s.scored_at)>=datetime(?) AND datetime(s.scored_at)<datetime(?)""",
            (user_id, start, end))
    return int((row or {}).get("n") or 0)

def period_key(quest: dict, now: datetime) -> str:
    return _window(quest["scope"], now)[0]

def get_quest(key: str) -> dict | None:
    return _BY_KEY.get(key)
