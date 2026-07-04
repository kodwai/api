from __future__ import annotations

import pytest

from app.operator_scoring.config import (
    GraderConfig,
    IrtConfig,
    LiftConfig,
    MutationConfig,
    OperatorScoringConfig,
    PersistenceConfig,
    PredictiveConfig,
    resolve_config,
)
from tests.operator_scoring.conftest import approx

# --- resolve_config: fallback + never-raises ---------------------------------

def test_none_empty_and_garbage_all_yield_defaults():
    default = OperatorScoringConfig()
    assert resolve_config(None) == default
    assert resolve_config("{}") == default
    assert resolve_config("garbage{") == default
    assert resolve_config("") == default
    assert resolve_config("   ") == default


def test_resolve_never_raises_on_bad_input():
    # None of these may raise; each degrades to valid config.
    for bad in [None, "", "garbage{", "[1,2,3]", "42", "null", 12345, object()]:
        cfg = resolve_config(bad)  # type: ignore[arg-type]
        assert isinstance(cfg, OperatorScoringConfig)


def test_invalid_values_fall_back_to_defaults():
    # An out-of-range value trips __post_init__ inside resolve_config, which
    # swallows it and returns full defaults rather than raising.
    cfg = resolve_config({"irt": {"tau2": -5.0}})
    assert cfg == OperatorScoringConfig()


# --- str / dict equivalence + override + unknown keys ------------------------

def test_str_and_dict_equivalence():
    d = {"irt": {"tau2": 2.0}, "lift": {"default_mu0": 0.4}}
    assert resolve_config('{"irt": {"tau2": 2.0}, "lift": {"default_mu0": 0.4}}') == resolve_config(d)


def test_partial_override_keeps_other_defaults():
    cfg = resolve_config({"irt": {"tau2": 3.0}})
    assert cfg.irt.tau2 == 3.0
    assert cfg.irt.z == 1.96          # untouched default
    assert cfg.lift.default_mu0 == 0.55  # untouched sibling section


def test_unknown_keys_ignored():
    cfg = resolve_config({
        "irt": {"tau2": 2.5, "totally_unknown": 999},
        "not_a_section": {"x": 1},
        "predictive": {"sigma_reg": 0.02, "junk": [1, 2, 3]},
    })
    assert cfg.irt.tau2 == 2.5
    assert cfg.predictive.sigma_reg == 0.02
    assert not hasattr(cfg.irt, "totally_unknown")


def test_json_arrays_coerced_to_tuples():
    cfg = resolve_config({"predictive": {
        "gamma": [-0.5, 1.0, 0.3, -0.1],
        "feature_names": ["theta", "v", "agent"],
    }})
    assert cfg.predictive.gamma == (-0.5, 1.0, 0.3, -0.1)
    assert isinstance(cfg.predictive.gamma, tuple)
    assert isinstance(cfg.predictive.feature_names, tuple)


def test_nested_mutation_config_resolves():
    cfg = resolve_config({"grader": {"replays": 5, "mutation": {"kill_rate_threshold": 0.9}}})
    assert cfg.grader.replays == 5
    assert isinstance(cfg.grader.mutation, MutationConfig)
    assert cfg.grader.mutation.kill_rate_threshold == 0.9
    assert cfg.grader.mutation.replays == 1  # untouched default


def test_top_level_scalars():
    cfg = resolve_config({"profile": "balanced", "version": 2, "rng_seed": 99})
    assert cfg.version == 2
    assert cfg.rng_seed == 99


# --- __post_init__ range validation ------------------------------------------

def test_irt_rejects_nonpositive_tau2():
    with pytest.raises(ValueError):
        IrtConfig(tau2=0.0)
    with pytest.raises(ValueError):
        IrtConfig(tau2=-1.0)


def test_irt_rejects_nonpositive_z():
    with pytest.raises(ValueError):
        IrtConfig(z=0.0)
    with pytest.raises(ValueError):
        IrtConfig(z=-0.5)


def test_predictive_rejects_nonpositive_z():
    with pytest.raises(ValueError):
        PredictiveConfig(z=0.0)


def test_lift_rejects_ceiling_equal_mu0():
    with pytest.raises(ValueError):
        LiftConfig(default_ceiling=0.55, default_mu0=0.55)


def test_predictive_rejects_gamma_feature_length_mismatch():
    with pytest.raises(ValueError):
        PredictiveConfig(gamma=(-0.8, 1.1, 0.6), feature_names=("theta", "v", "agent"))


def test_grader_rejects_bad_enums_and_replays():
    with pytest.raises(ValueError):
        GraderConfig(weight_policy="bogus")
    with pytest.raises(ValueError):
        GraderConfig(on_check_error="explode")
    with pytest.raises(ValueError):
        GraderConfig(replays=0)


def test_persistence_json_requires_path():
    with pytest.raises(ValueError):
        PersistenceConfig(item_backend="json", item_path=None)
    with pytest.raises(ValueError):
        PersistenceConfig(calibration_backend="json", calibration_path=None)
    # memory backend needs no path
    assert PersistenceConfig().item_backend == "memory"


def test_lift_crn_rho_is_clamped_not_rejected():
    assert LiftConfig(crn_rho=5.0).crn_rho == 1.0
    assert LiftConfig(crn_rho=-2.0).crn_rho == 0.0


# --- defaults match the acceptance oracle (SCORING_DESIGN sections 4 & 12) ----

def test_grader_defaults():
    g = GraderConfig()
    assert g.replays == 3
    assert g.weight_policy == "normalize"
    assert g.on_check_error == "zero"
    assert g.flakiness_metric == "aggregate_stdev"
    assert g.flakiness_penalty_weight == 1.0
    assert g.display_dp == 4
    assert g.allowed_kinds == (
        "functional", "edge_adversarial", "property_invariants",
        "performance", "security_fuzz",
    )
    assert g.mutation.kill_rate_threshold == 0.80
    assert g.mutation.replays == 1


def test_lift_defaults_match_oracle_E():
    lift = LiftConfig()
    assert approx(lift.sigma_intrinsic, 0.10)
    assert approx(lift.default_ceiling, 0.97)
    assert lift.default_M == 20
    assert approx(lift.default_mu0, 0.55)
    assert approx(lift.default_sigma0, 0.08)


def test_irt_defaults_match_oracle_D():
    irt = IrtConfig()
    assert irt.tau2 == 1.0
    assert irt.z == 1.96
    assert irt.dims == ("dec", "ver", "rec", "taste", "eff")
    assert irt.theta_bounds == (-6.0, 6.0)


def test_predictive_defaults_match_oracle_G():
    p = PredictiveConfig()
    assert p.gamma == (-0.80, 1.10, 0.60, -0.15)
    assert p.feature_names == ("theta", "v", "agent")
    assert approx(p.sigma_reg, 0.05)
    assert p.z == 1.96
    assert p.calibration_method == "none"
    assert len(p.gamma) == len(p.feature_names) + 1


def test_top_level_defaults():
    cfg = OperatorScoringConfig()
    assert cfg.profile == "balanced"
    assert cfg.version == 1
    assert cfg.rng_seed == 0
    assert isinstance(cfg.grader, GraderConfig)
    assert isinstance(cfg.persistence, PersistenceConfig)
