from datetime import datetime, timezone, timedelta
from app.services.scoring.engine import compute_streak

def _iso(d): return d.strftime("%Y-%m-%d %H:%M:%S")

def test_first_ever_is_one():
    assert compute_streak(0, None) == 1

def test_same_day_keeps_streak():
    assert compute_streak(5, _iso(datetime.now(timezone.utc))) == 5

def test_consecutive_day_increments():
    assert compute_streak(5, _iso(datetime.now(timezone.utc) - timedelta(days=1))) == 6

def test_gap_resets_to_one():
    assert compute_streak(5, _iso(datetime.now(timezone.utc) - timedelta(days=3))) == 1

def test_same_day_zero_becomes_one():
    assert compute_streak(0, _iso(datetime.now(timezone.utc))) == 1
