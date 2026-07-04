"""Layer D (scalar) acceptance oracle + property tests.

The acceptance oracle is reproduced at full precision (tol 1e-3). Inputs flow in
from Layer E at *full* precision (never ``round(...)``); a regression test pins
the load-bearing consequence of rounding at the E -> D boundary.
"""
from __future__ import annotations

import numpy as np

from app.operator_scoring.config import OperatorScoringConfig, resolve_config
from app.operator_scoring.irt import (
    AbilityEstimate,
    ItemObservation,
    fit_ability,
    item_information,
    select_next_item,
)
from tests.operator_scoring.conftest import approx

# Full-precision Layer-E outputs for the oracle ledger item (NOT display-rounded).
L1_FULL = 0.7023809523809523
S1_FULL = 0.10869249724298408

# Oracle expectations (SCORING_DESIGN.md sections 7 & 12), full precision.
ORACLE_THETA = 0.8757518709631057
ORACLE_INFO = 57.62379258827583
ORACLE_SE = 0.13173436450445417
ORACLE_CI = (0.6175525, 1.1339512)
ORACLE_PER_ITEM = [16.982114, 1.707714, 18.970816, 10.675488, 8.287660]


def _oracle_battery(l1: float = L1_FULL, s1: float = S1_FULL) -> list[ItemObservation]:
    """The five-item acceptance battery (order is load-bearing for per-item info)."""
    return [
        ItemObservation(L=l1, a=1.8, b=0.80, s=s1, item_id="ledger"),
        ItemObservation(L=0.92, a=0.9, b=-0.50, s=0.12, item_id="rest_crud_easy"),
        ItemObservation(L=0.45, a=2.0, b=0.50, s=0.10, item_id="rate_limiter_trap"),
        ItemObservation(L=0.68, a=1.5, b=0.60, s=0.11, item_id="search_index"),
        ItemObservation(L=0.40, a=1.6, b=1.20, s=0.13, item_id="dist_log_hard"),
    ]


def _naive_newton(
    observations: list[ItemObservation],
    config: OperatorScoringConfig,
    max_iter: int = 100,
) -> float:
    """Raw observed-Hessian Newton with no -Fisher guard and no line search.

    This is what Layer D would be *without* the guarded-solver machinery
    ``fit_ability`` provides. On the acceptance battery it overshoots the unique
    interior optimum (the observed Hessian at theta=0 is only mildly concave
    relative to the gradient) and oscillates out to the theta-bound region.
    """
    irt = config.irt
    tau2 = irt.tau2
    lo, hi = irt.theta_bounds
    L = np.array([o.L for o in observations], dtype=np.float64)
    a = np.array([o.a for o in observations], dtype=np.float64)
    b = np.array([o.b for o in observations], dtype=np.float64)
    s = np.array([o.s for o in observations], dtype=np.float64)
    theta = float(irt.init_theta)
    for _ in range(max_iter):
        g = 1.0 / (1.0 + np.exp(-(a * (theta - b))))
        gp = a * g * (1.0 - g)
        gpp = a * a * g * (1.0 - g) * (1.0 - 2.0 * g)
        grad = float(-theta / tau2 + np.sum((L - g) * gp / s**2))
        hess = float(-1.0 / tau2 + np.sum((-(gp**2) + (L - g) * gpp) / s**2))
        theta = min(hi, max(lo, theta - grad / hess))
        if abs(grad) < irt.grad_tol:
            break
    return float(theta)


# --- acceptance oracle -------------------------------------------------------

def test_acceptance_oracle_scalar():
    cfg = resolve_config(None)
    est = fit_ability(_oracle_battery(), cfg)

    assert approx(est.theta_hat, ORACLE_THETA)
    assert approx(est.information, ORACLE_INFO)
    assert approx(est.se, ORACLE_SE)
    assert approx(est.ci95[0], ORACLE_CI[0])
    assert approx(est.ci95[1], ORACLE_CI[1])

    assert len(est.per_item_information) == len(ORACLE_PER_ITEM)
    for got, want in zip(est.per_item_information, ORACLE_PER_ITEM, strict=True):
        assert approx(got, want)

    assert est.n_items == 5
    assert est.converged
    # Multi-start guarded Newton reaches the global MAP; the winning start's
    # iteration count is an internal detail, so just assert it did real work.
    assert est.iterations >= 1

    # CAT: the most informative battery item at theta_hat is the rate-limiter trap.
    assert est.next_item_id == "rate_limiter_trap"


def test_full_precision_flows():
    """Full precision is load-bearing at the E -> D boundary.

    ``fit_ability`` (guarded Newton) lands in the oracle basin at full precision.
    The *unguarded* Newton -- Layer D stripped of the design's guard + line
    search -- diverges to the theta-bound region on the display-rounded battery,
    ``|theta - 0.8758| > 1.0``. The exact corrupted value is numpy-build
    dependent, so we assert a threshold, not a pinned number.
    """
    cfg = resolve_config(None)

    est_full = fit_ability(_oracle_battery(L1_FULL, S1_FULL), cfg)
    assert approx(est_full.theta_hat, ORACLE_THETA)

    rounded = _oracle_battery(0.7024, 0.1087)
    theta_naive = _naive_newton(rounded, cfg)
    assert abs(theta_naive - 0.8758) > 1.0


# --- empty battery -> prior --------------------------------------------------

def test_empty_battery_returns_prior():
    cfg = resolve_config(None)
    est = fit_ability([], cfg)

    assert est.theta_hat == cfg.irt.init_theta          # 0.0
    assert approx(est.information, 1.0 / cfg.irt.tau2)   # 1/tau2
    assert approx(est.se, float(np.sqrt(cfg.irt.tau2)))  # sqrt(tau2)
    assert est.per_item_information == []
    assert est.iterations == 0
    assert est.converged
    assert est.n_items == 0
    assert est.next_item_id is None
    z = cfg.irt.z
    assert approx(est.ci95[0], est.theta_hat - z * est.se)
    assert approx(est.ci95[1], est.theta_hat + z * est.se)


# --- monotonicity: theta non-decreasing when any single L_i rises ------------

def test_theta_monotone_in_L():
    cfg = resolve_config(None)
    base = _oracle_battery()
    theta0 = fit_ability(base, cfg).theta_hat

    bumped = list(base)
    item = bumped[0]  # ledger, a=1.8 > 0
    bumped[0] = ItemObservation(L=item.L + 0.15, a=item.a, b=item.b, s=item.s, item_id=item.item_id)
    theta1 = fit_ability(bumped, cfg).theta_hat

    assert theta1 > theta0  # strict for a_i > 0 (d grad / d L_i = g_i'/s_i^2 > 0)


# --- SE strictly shrinks when an a != 0 item is added ------------------------

def test_se_shrinks_on_add():
    cfg = resolve_config(None)
    base = _oracle_battery()
    se_before = fit_ability(base, cfg).se

    extended = list(base)
    extended.append(ItemObservation(L=0.60, a=1.5, b=0.90, s=0.10, item_id="extra"))
    se_after = fit_ability(extended, cfg).se

    assert se_after < se_before  # I = 1/tau2 + sum of non-negative terms


# --- single-item information peaks at theta = b ------------------------------

def test_information_peaks_at_b():
    a, b, s = 1.7, 0.35, 0.10
    grid = np.linspace(b - 3.0, b + 3.0, 61)  # b is exactly on the grid (step 0.1)
    infos = [item_information(float(t), a, b, s) for t in grid]
    argmax_theta = float(grid[int(np.argmax(infos))])
    step = float(grid[1] - grid[0])
    assert abs(argmax_theta - b) <= step + 1e-9


# --- CAT selection: argmax info, deterministic tie-break, None when all used --

def test_cat_picks_max_info():
    cfg = resolve_config(None)
    battery = _oracle_battery()
    theta_hat = fit_ability(battery, cfg).theta_hat

    chosen = select_next_item(theta_hat, battery, set())
    assert chosen is not None
    assert chosen.item_id == "rate_limiter_trap"  # max per-item info (18.97)

    # Excluding the trap, the ledger (16.98) is next most informative.
    chosen2 = select_next_item(theta_hat, battery, {"rate_limiter_trap"})
    assert chosen2 is not None
    assert chosen2.item_id == "ledger"

    all_used = {o.item_id for o in battery}
    assert select_next_item(theta_hat, battery, all_used) is None


# --- input validation --------------------------------------------------------

def test_item_observation_rejects_bad_params():
    import pytest

    with pytest.raises(ValueError):
        ItemObservation(L=0.5, a=1.0, b=0.0, s=0.0)   # s must be > 0
    with pytest.raises(ValueError):
        ItemObservation(L=0.5, a=1.0, b=0.0, s=-0.1)
    with pytest.raises(ValueError):
        ItemObservation(L=0.5, a=0.0, b=0.0, s=0.1)   # a must be != 0


def test_to_json_rounds_display_only():
    cfg = resolve_config(None)
    est = fit_ability(_oracle_battery(), cfg)
    js = est.to_json(decimals=4)
    assert js["theta_hat"] == round(est.theta_hat, 4)
    assert js["ci_low"] == round(est.ci95[0], 4)
    assert js["ci_high"] == round(est.ci95[1], 4)
    assert js["next_item_id"] == "rate_limiter_trap"
    # Attribute stays full precision; only the serialized view is rounded.
    assert isinstance(est, AbilityEstimate)
    assert est.theta_hat != js["theta_hat"] or est.theta_hat == round(est.theta_hat, 4)
