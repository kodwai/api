from __future__ import annotations

import math

import numpy as np

from app.operator_scoring.config import OperatorScoringConfig, resolve_config
from app.operator_scoring.lift import (
    BaselineStats,
    LiftResult,
    compute_lift,
    estimate_baseline,
    resolve_mu_star,
)

# --- the acceptance oracle (full precision, tol 1e-12) -----------------------

L1_EXPECTED = 0.7023809523809523
S1_EXPECTED = 0.10869249724298408


def test_lift_oracle():
    cfg = OperatorScoringConfig()
    result = compute_lift(0.845, BaselineStats(0.55, 0.08, 20), 0.97, 0.10, cfg)
    assert isinstance(result, LiftResult)
    assert abs(result.L - L1_EXPECTED) <= 1e-12
    assert abs(result.s - S1_EXPECTED) <= 1e-12
    # mu_star / mu0 carried through, item not degenerate, no CRN on the oracle path.
    assert result.mu_star == 0.97
    assert result.mu0 == 0.55
    assert result.ceiling_degenerate is False
    assert result.crn_applied is False


# --- L is unclipped ----------------------------------------------------------

def test_lift_unclipped_below_zero():
    cfg = OperatorScoringConfig()
    # O below the baseline mean => L < 0 (not clipped to 0).
    result = compute_lift(0.30, BaselineStats(0.55, 0.08, 20), 0.97, 0.10, cfg)
    assert result.L < 0.0
    assert abs(result.L - (0.30 - 0.55) / (0.97 - 0.55)) <= 1e-12


def test_lift_unclipped_above_one():
    cfg = OperatorScoringConfig()
    # O above the ceiling gap => L > 1 (not clipped to 1).
    result = compute_lift(0.99, BaselineStats(0.55, 0.08, 20), 0.97, 0.10, cfg)
    assert result.L > 1.0
    assert abs(result.L - (0.99 - 0.55) / (0.97 - 0.55)) <= 1e-12


def test_lift_zero_at_mu0():
    cfg = OperatorScoringConfig()
    result = compute_lift(0.55, BaselineStats(0.55, 0.08, 20), 0.97, 0.10, cfg)
    assert result.L == 0.0


def test_lift_one_at_ceiling():
    cfg = OperatorScoringConfig()
    result = compute_lift(0.97, BaselineStats(0.55, 0.08, 20), 0.97, 0.10, cfg)
    assert abs(result.L - 1.0) <= 1e-12


# --- s shrinks with more replays and a wider gap -----------------------------

def test_s_decreases_with_M():
    cfg = OperatorScoringConfig()
    s_small_m = compute_lift(0.845, BaselineStats(0.55, 0.08, 5), 0.97, 0.10, cfg).s
    s_large_m = compute_lift(0.845, BaselineStats(0.55, 0.08, 50), 0.97, 0.10, cfg).s
    assert s_large_m < s_small_m


def test_s_decreases_with_gap():
    cfg = OperatorScoringConfig()
    # Wider ceiling gap (0.97-0.55=0.42) => smaller baseline-mean SE on the L
    # scale => smaller s than a narrow gap (0.65-0.55=0.10).
    s_wide = compute_lift(0.60, BaselineStats(0.55, 0.08, 20), 0.97, 0.10, cfg).s
    s_narrow = compute_lift(0.60, BaselineStats(0.55, 0.08, 20), 0.65, 0.10, cfg).s
    assert s_wide < s_narrow


# --- CRN paired-variance reduction -------------------------------------------

def test_crn_reduces_s():
    seeds = tuple(range(20))
    baseline = BaselineStats(0.55, 0.08, 20, crn_seeds=seeds)
    base_cfg = OperatorScoringConfig()
    crn_cfg = resolve_config({"lift": {"crn_enabled": True, "crn_rho": 0.5}})

    base = compute_lift(0.845, baseline, 0.97, 0.10, base_cfg)
    crn = compute_lift(0.845, baseline, 0.97, 0.10, crn_cfg)

    assert base.crn_applied is False
    assert crn.crn_applied is True
    assert crn.s < base.s
    # rho=0 with pairing recovers the base formula exactly.
    crn_rho0 = resolve_config({"lift": {"crn_enabled": True, "crn_rho": 0.0}})
    recovered = compute_lift(0.845, baseline, 0.97, 0.10, crn_rho0)
    assert recovered.crn_applied is True
    assert abs(recovered.s - base.s) <= 1e-12


def test_crn_not_applied_without_seeds():
    # crn_enabled but no threaded seeds => reduction does not apply.
    crn_cfg = resolve_config({"lift": {"crn_enabled": True, "crn_rho": 0.5}})
    result = compute_lift(0.845, BaselineStats(0.55, 0.08, 20), 0.97, 0.10, crn_cfg)
    assert result.crn_applied is False


# --- degenerate ceiling self-mutes with a finite (huge) s --------------------

def test_degenerate_ceiling_finite():
    cfg = OperatorScoringConfig()
    # Baseline >= ceiling => degenerate gap.
    result = compute_lift(0.60, BaselineStats(0.55, 0.08, 20), 0.50, 0.10, cfg)
    assert result.ceiling_degenerate is True
    assert result.L == 0.0
    assert result.s == cfg.lift.max_se
    assert math.isfinite(result.s)

    star, degenerate = resolve_mu_star(0.55, 0.55, cfg)
    assert star == 0.55
    assert degenerate is True


def test_resolve_mu_star_non_degenerate():
    cfg = OperatorScoringConfig()
    star, degenerate = resolve_mu_star(0.97, 0.55, cfg)
    assert star == 0.97
    assert degenerate is False


# --- estimate_baseline is deterministic under a seeded generator -------------

class _SeedRunner:
    """Deterministic baseline runner: outcome is a fixed function of the seed."""

    def __call__(self, item: object, seed: int) -> float:
        # A bounded, seed-dependent value in [0, 1], no entropy of its own.
        return ((seed % 1000) / 1000.0) * 0.5 + 0.25


def test_estimate_baseline_deterministic():
    runner = _SeedRunner()
    cfg = OperatorScoringConfig()

    a = estimate_baseline(runner, object(), 20, np.random.default_rng(123), cfg)
    b = estimate_baseline(runner, object(), 20, np.random.default_rng(123), cfg)

    assert a.M == 20 == b.M
    assert a.mu0 == b.mu0
    assert a.sigma0 == b.sigma0
    assert a.raw_scores == b.raw_scores
    assert 0.0 <= a.mu0 <= 1.0
    assert a.sigma0 >= 0.0


def test_estimate_baseline_prior_sigma_fallback_single_replay():
    runner = _SeedRunner()
    cfg = OperatorScoringConfig()
    stats = estimate_baseline(runner, object(), 1, np.random.default_rng(7), cfg)
    # M < 2 => sample stdev is undefined, so sigma0 falls back to prior.
    assert stats.M == 1
    assert stats.sigma0 == cfg.lift.prior_sigma0


def test_estimate_baseline_threads_seeds_when_crn_enabled():
    runner = _SeedRunner()
    crn_cfg = resolve_config({"lift": {"crn_enabled": True}})
    stats = estimate_baseline(runner, object(), 8, np.random.default_rng(5), crn_cfg)
    assert len(stats.crn_seeds) == 8
    # Without CRN the seeds are not threaded.
    plain = estimate_baseline(runner, object(), 8, np.random.default_rng(5), OperatorScoringConfig())
    assert plain.crn_seeds == ()


# --- to_json rounds for display only; fields stay full precision -------------

def test_to_json_rounds_display_only():
    cfg = OperatorScoringConfig()
    result = compute_lift(0.845, BaselineStats(0.55, 0.08, 20), 0.97, 0.10, cfg)
    payload = result.to_json()

    # The dataclass field keeps full precision; only the JSON view is rounded.
    assert result.L == L1_EXPECTED
    assert result.s == S1_EXPECTED
    assert payload["L"] != result.L
    assert payload["s"] != result.s
    assert payload["L"] == round(result.L, 4)
    assert payload["s"] == round(result.s, 4)
    assert payload["L"] == 0.7024
    assert payload["s"] == 0.1087


def test_to_json_custom_decimals():
    cfg = OperatorScoringConfig()
    result = compute_lift(0.845, BaselineStats(0.55, 0.08, 20), 0.97, 0.10, cfg)
    assert result.to_json(decimals=6)["L"] == round(L1_EXPECTED, 6)


def test_baseline_stats_to_json_rounds():
    stats = BaselineStats(0.5551234567, 0.0812345678, 3, raw_scores=(0.1234567, 0.2, 0.3))
    payload = stats.to_json()
    assert payload["M"] == 3
    assert payload["mu0"] == round(0.5551234567, 6)
    assert payload["raw_scores"][0] == round(0.1234567, 6)
