from app.services.scoring.engine import update_rating


def test_new_dev_defaults_1000_and_gains_on_good_hard():
    assert update_rating(None, "hard", 90) > 1000


def test_low_score_loses():
    assert update_rating(1000, "easy", 0) < 1000


def test_floor_100():
    assert update_rating(120, "easy", 0) >= 100


def test_harder_challenge_more_gain_for_same_score():
    base = 1000
    assert (update_rating(base, "hard", 80) - base) > (update_rating(base, "easy", 80) - base)


def test_perfect_easy_at_high_rating_barely_moves():
    assert abs(update_rating(2000, "easy", 100) - 2000) <= 2
