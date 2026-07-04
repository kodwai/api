"""Regression tests for the robustness fixes surfaced by adversarial verification.

Each test pins a defect that was found and fixed:
  * scalar Layer-D single-start Newton could return a non-global / minimum MAP;
  * compute_lift could emit ``s == 0`` (rejected downstream);
  * a non-finite ``L`` silently collapsed a whole battery to the prior;
  * JsonItemRepository crashed on a malformed file;
  * compute_lift did not clamp an out-of-range ``O``;
  * fit_ability_md overshot without a line search.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.operator_scoring.config import resolve_config
from app.operator_scoring.irt import IrtError, ItemObservation, fit_ability
from app.operator_scoring.irt_md import dimension_observation, fit_ability_md
from app.operator_scoring.itembank import JsonItemRepository
from app.operator_scoring.lift import BaselineStats, compute_lift


def _arrays(obs):
    return (
        np.array([o.L for o in obs]),
        np.array([o.a for o in obs]),
        np.array([o.b for o in obs]),
        np.array([o.s for o in obs]),
    )


def _logpost(theta, obs, tau2=1.0):
    """MAP log-posterior at a scalar theta (matches irt._log_posterior)."""
    ell, a, b, s = _arrays(obs)
    g = 1.0 / (1.0 + np.exp(-a * (theta - b)))
    return float(-theta * theta / (2 * tau2) - np.sum((ell - g) ** 2 / (2 * s * s)))


def _brute(obs, tau2=1.0):
    """Global MAP by a vectorized grid scan (ground truth for the multi-start solver)."""
    ell, a, b, s = _arrays(obs)
    grid = np.linspace(-6.0, 6.0, 24001)[:, None]
    g = 1.0 / (1.0 + np.exp(-a * (grid - b)))
    lp = -grid[:, 0] ** 2 / (2 * tau2) - np.sum((ell - g) ** 2 / (2 * s * s), axis=1)
    return float(grid[int(np.argmax(lp)), 0])


# --- Layer D: multi-start finds the GLOBAL MAP (was a single-start local mode) ---

def test_fit_ability_finds_global_map_on_bimodal_battery():
    """Conflicting evidence makes the posterior bimodal; a single start from 0 misses
    the global mode. Multi-start must match the brute-force global argmax."""
    cfg = resolve_config(None)
    obs = [
        ItemObservation(0.05, 2.5, -1.5, 0.08, "easy_low"),
        ItemObservation(0.98, 2.5, 2.0, 0.08, "hard_high"),
    ]
    est = fit_ability(obs, cfg)
    gt = _brute(obs)
    assert abs(est.theta_hat - gt) < 5e-2
    # The global mode is far from the prior mean 0 (a single start from 0 would stall low).
    assert est.theta_hat > 2.0
    assert est.converged


def test_fit_ability_not_stuck_at_symmetric_minimum():
    """At a symmetric configuration theta=0 is a stationary point; converged must be
    honest (only True at a genuine maximum) and the returned theta must be a max."""
    cfg = resolve_config(None)
    obs = [
        ItemObservation(0.95, 2.0, -1.0, 0.10, "a"),
        ItemObservation(0.05, 2.0, 1.0, 0.10, "b"),
    ]
    est = fit_ability(obs, cfg)
    # theta must be at least as good (log-posterior) as any brute-force grid point.
    assert _logpost(est.theta_hat, obs) >= _logpost(_brute(obs), obs) - 1e-9
    assert est.converged


def test_fit_ability_matches_brute_force_on_random_batteries():
    """Across many seeded batteries the multi-start MAP never underperforms the grid."""
    cfg = resolve_config(None)
    rng = np.random.default_rng(2024)
    for _ in range(60):
        k = int(rng.integers(1, 5))
        obs = [
            ItemObservation(
                float(rng.uniform(-0.3, 1.3)), float(rng.uniform(0.5, 2.5)),
                float(rng.uniform(-2, 2)), float(rng.uniform(0.05, 0.25)),
            )
            for _ in range(k)
        ]
        est = fit_ability(obs, cfg)
        assert _logpost(est.theta_hat, obs) >= _logpost(_brute(obs), obs) - 1e-3


# --- Layer D: non-finite L is rejected, not silently absorbed ---

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_item_observation_rejects_non_finite_L(bad):
    with pytest.raises(IrtError):
        ItemObservation(bad, 1.5, 0.0, 0.1)


# --- Layer E: s is floored so it never crashes Layer D; O is clamped ---

def test_compute_lift_floors_s_on_zero_variance_baseline():
    """sigma_intrinsic == 0 and a zero-variance baseline must not yield s == 0."""
    cfg = resolve_config(None)
    baseline = BaselineStats(mu0=0.55, sigma0=0.0, M=20)
    res = compute_lift(0.845, baseline, 0.97, 0.0, cfg)
    assert res.s >= cfg.lift.min_s > 0.0
    # And Layer D accepts the resulting observation (would raise if s == 0).
    fit_ability([ItemObservation(res.L, 1.8, 0.8, res.s)], cfg)


def test_compute_lift_clamps_out_of_range_outcome():
    """An out-of-range O is clamped to [0, 1]; L past the ceiling stays unclipped (>1)."""
    cfg = resolve_config(None)
    baseline = BaselineStats(mu0=0.55, sigma0=0.08, M=20)
    at_one = compute_lift(1.0, baseline, 0.97, 0.10, cfg)
    huge = compute_lift(10.0, baseline, 0.97, 0.10, cfg)
    assert huge.L == at_one.L        # O=10 clamped to O=1
    assert at_one.L > 1.0            # beating the ceiling is still representable


# --- item bank: malformed JSON is tolerated (mirrors the calibration store) ---

def test_json_item_repo_tolerates_malformed_file(tmp_path):
    path = tmp_path / "items.json"
    path.write_text("{not valid json", encoding="utf-8")
    repo = JsonItemRepository(str(path))
    assert repo.list() == []                       # empty store, no crash


def test_json_item_repo_skips_invalid_records(tmp_path):
    path = tmp_path / "items.json"
    # One valid item and one invalid (a <= 0) record in the same file.
    path.write_text(
        '[{"id": "ok", "a": 1.5, "b": 0.2}, {"id": "bad", "a": -1.0, "b": 0.0}]',
        encoding="utf-8",
    )
    repo = JsonItemRepository(str(path))
    ids = [it.id for it in repo.list()]
    assert ids == ["ok"]                            # valid item kept, bad one skipped


# --- Layer D (MD): the Fisher-scoring line search converges (was overshooting) ---

def test_fit_ability_md_line_search_converges():
    """A realistic 1-D battery that overshoot without a line search now converges
    to the same mode as the scalar solver."""
    cfg = resolve_config(None)
    scalar = [
        ItemObservation(0.9, 2.2, -1.5, 0.06),
        ItemObservation(0.15, 2.4, 1.3, 0.06),
        ItemObservation(0.6, 1.7, 0.2, 0.09),
    ]
    est_scalar = fit_ability(scalar, cfg)
    md = [dimension_observation(0, o.L, o.a, o.b, o.s, 1) for o in scalar]
    est_md = fit_ability_md(md, cfg, dims=1)
    assert est_md.converged
    assert abs(est_md.theta_hat[0] - est_scalar.theta_hat) < 1e-4
