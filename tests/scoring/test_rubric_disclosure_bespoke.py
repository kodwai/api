"""Regression: build_rubric must surface the bespoke per-challenge rubric so the
pre-challenge 'How you're scored' card shows the actual scoring dimensions, not
just the profile's generic outcome signals."""
from app.services.scoring.config import build_rubric


def test_bespoke_rubric_surfaces_as_challenge_rubric_axis():
    cfg = {
        "profile": "spec_heavy",
        "rubric": [
            {"name": "Functional Correctness", "weight": 10,
             "description": "Works as specified. **2/10**: barely runs. **5/10**: happy path only. **8/10**: edges handled. **10/10**: everything."},
            {"name": "API Design", "weight": 6,
             "description": "Endpoints + status codes are right. **2/10**: random. **5/10**: REST-ish. **8/10**: clean. **10/10**: textbook."},
        ],
    }
    out = build_rubric(cfg)
    axis_names = {a["name"] for a in out["axes"]}
    assert "challenge_rubric" in axis_names, "bespoke rubric not surfaced"
    # In bespoke mode the generic outcome axis is replaced by the rubric axis.
    assert "outcome" not in axis_names, "outcome axis should be replaced when rubric is present"
    rubric_axis = next(a for a in out["axes"] if a["name"] == "challenge_rubric")
    assert rubric_axis["points"] == 45
    labels = {s["label"] for s in rubric_axis["signals"]}
    assert labels == {"Functional Correctness", "API Design"}
    # Each dim's anchored description survives so candidates see what 10/10 means.
    fc = next(s for s in rubric_axis["signals"] if s["label"] == "Functional Correctness")
    assert "10/10" in fc["description"]


def test_direction_and_lift_rescaled_to_bespoke_layout():
    cfg = {"profile": "spec_heavy", "rubric": [{"name": "X", "weight": 5, "description": "x"}]}
    out = build_rubric(cfg)
    direction = next(a for a in out["axes"] if a["name"] == "direction")
    lift = next(a for a in out["axes"] if a["name"] == "lift")
    # Engine bespoke layout: direction 45, rubric 45, lift 10.
    assert direction["points"] == 45
    assert lift["points"] == 10


def test_no_rubric_keeps_legacy_profile_layout():
    # When no bespoke rubric, build_rubric must still return the profile's axes
    # (direction/outcome/lift) with their original points — no behaviour change.
    out = build_rubric({"profile": "balanced"})
    axis_names = {a["name"] for a in out["axes"]}
    assert axis_names == {"direction", "outcome", "lift"}
    direction = next(a for a in out["axes"] if a["name"] == "direction")
    assert direction["points"] == 50  # balanced default
