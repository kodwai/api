from app.services.scoring.config import resolve_config, DEFAULT_PROFILES


def test_empty_falls_back_to_balanced():
    cfg = resolve_config("{}")
    assert cfg.profile == "balanced"
    assert cfg.axes["direction"].points == 50
    assert cfg.axes["outcome"].points == 35
    assert cfg.axes["lift"].points == 15


def test_none_falls_back_to_balanced():
    assert resolve_config(None).profile == "balanced"


def test_named_profile_inherits_axes():
    cfg = resolve_config('{"profile": "debugging"}')
    assert cfg.profile == "debugging"
    assert cfg.axes["direction"].points == 60
    assert cfg.axes["direction"].signals["recovery"] == 1.4


def test_unknown_profile_falls_back():
    cfg = resolve_config('{"profile": "nope"}')
    assert cfg.profile == "balanced"


def test_explicit_axes_override_profile():
    cfg = resolve_config({"profile": "balanced", "axes": {
        "outcome": {"points": 100, "signals": {"tests": 1.0}}
    }})
    assert cfg.axes["outcome"].points == 100
    assert "direction" not in cfg.axes


def test_traps_parsed():
    cfg = resolve_config({"profile": "balanced", "traps": [
        {"id": "empty", "description": "handle empty input"}
    ]})
    assert cfg.traps[0].id == "empty"


def test_profiles_sum_to_100():
    for name, prof in DEFAULT_PROFILES.items():
        total = sum(a["points"] for a in prof["axes"].values())
        assert total == 100, f"{name} sums to {total}"
