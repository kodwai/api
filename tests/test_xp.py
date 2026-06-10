from app.services.xp import submission_xp, level_for

def test_submission_xp():
    assert submission_xp(90, "hard") == 180     # 90 * 2.0
    assert submission_xp(50, "easy") == 50      # 50 * 1.0
    assert submission_xp(80, "medium") == 120   # 80 * 1.5
    assert submission_xp(None, "hard") == 0
    assert submission_xp(150, "easy") == 100    # clamped to 100

def test_level_for_thresholds():
    assert level_for(0)["level"] == 1
    assert level_for(99)["level"] == 1
    assert level_for(100)["level"] == 2
    assert level_for(299)["level"] == 2
    assert level_for(300)["level"] == 3
    assert level_for(599)["level"] == 3
    assert level_for(600)["level"] == 4

def test_level_for_progress():
    lf = level_for(200)   # level 2: floor 100, next 300
    assert lf["level"] == 2 and lf["level_floor"] == 100 and lf["next_level_xp"] == 300
    assert 0.49 <= lf["progress"] <= 0.51
