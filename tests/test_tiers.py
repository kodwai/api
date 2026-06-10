from app.services.tiers import tier_for


def test_default_and_low_is_silver_or_bronze():
    assert tier_for(1000)["key"] == "silver"
    assert tier_for(None)["key"] == "silver"   # default 1000
    assert tier_for(0)["key"] == "bronze"
    assert tier_for(999)["key"] == "bronze"


def test_thresholds():
    assert tier_for(1150)["key"] == "gold"
    assert tier_for(1299)["key"] == "gold"
    assert tier_for(1300)["key"] == "platinum"
    assert tier_for(1800)["key"] == "grandmaster"
    assert tier_for(5000)["key"] == "grandmaster"


def test_progress_and_next():
    g = tier_for(1150)
    assert g["next_name"] == "Platinum" and g["next_at"] == 1300
    assert 0.0 <= g["progress"] <= 0.05
    gm = tier_for(1900)
    assert gm["next_name"] is None and gm["progress"] == 1.0
