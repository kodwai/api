from app.services.scoring.registry import SIGNALS, get_signal
from app.services.scoring.config import DEFAULT_PROFILES


def test_every_profile_signal_is_registered():
    for prof in DEFAULT_PROFILES.values():
        for axis in prof["axes"].values():
            for name in axis["signals"]:
                assert name in SIGNALS, f"{name} missing from registry"


def test_get_signal_unknown_returns_none():
    assert get_signal("does_not_exist") is None
