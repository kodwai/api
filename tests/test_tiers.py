from app.services.tiers import tier_for, _DEFAULT_TIERS, load_tiers


def test_default_and_low_is_silver_or_bronze():
    assert tier_for(1000, _DEFAULT_TIERS)["key"] == "silver"
    assert tier_for(None, _DEFAULT_TIERS)["key"] == "silver"   # default 1000
    assert tier_for(0, _DEFAULT_TIERS)["key"] == "bronze"
    assert tier_for(999, _DEFAULT_TIERS)["key"] == "bronze"


def test_thresholds():
    assert tier_for(1150, _DEFAULT_TIERS)["key"] == "gold"
    assert tier_for(1299, _DEFAULT_TIERS)["key"] == "gold"
    assert tier_for(1300, _DEFAULT_TIERS)["key"] == "platinum"
    assert tier_for(1800, _DEFAULT_TIERS)["key"] == "grandmaster"
    assert tier_for(5000, _DEFAULT_TIERS)["key"] == "grandmaster"


def test_progress_and_next():
    g = tier_for(1150, _DEFAULT_TIERS)
    assert g["next_name"] == "Platinum" and g["next_at"] == 1300
    assert 0.0 <= g["progress"] <= 0.05
    gm = tier_for(1900, _DEFAULT_TIERS)
    assert gm["next_name"] is None and gm["progress"] == 1.0


def test_load_tiers_from_db():
    """DB-backed: migration 036 seeds the tiers table (fresh_db fixture is autouse)."""
    tiers = load_tiers()
    assert len(tiers) == 7
    gold = next(t for t in tiers if t["key"] == "gold")
    assert gold["min"] == 1150
