"""Layer D (multidimensional) tests.

The one-dimensional MD estimator must reproduce the scalar Layer-D oracle
(to <=1e-6), because ``dimension_observation`` folds the scalar difficulty
into the linear-predictor intercept (``b_MD = a * b_scalar``). Higher-dimensional
tests pin the structural invariants: the Fisher matrix is symmetric positive
definite, per-dimension SE is the diagonal of ``I^-1``, and an objective process
signal on the ``ver`` axis raises ``theta[ver]`` while shrinking ``se[ver]``.
"""
from __future__ import annotations

import numpy as np

from app.operator_scoring.config import resolve_config
from app.operator_scoring.irt import ItemObservation, fit_ability
from app.operator_scoring.irt_md import (
    AbilityEstimateMD,
    ItemObservationMD,
    dimension_observation,
    fit_ability_md,
    item_information_md,
    select_next_item_md,
)

# Scalar oracle expectations (SCORING_DESIGN.md sections 7 & 12), full precision.
ORACLE_THETA = 0.8757518709631057
ORACLE_INFO = 57.62379258827583
ORACLE_SE = 0.13173436450445417

# Full-precision Layer-E outputs for the oracle ledger item (NOT display-rounded).
L1_FULL = 0.7023809523809523
S1_FULL = 0.10869249724298408

# (L, a, b, s) for the five-item acceptance battery (order is load-bearing).
_BATTERY = [
    (L1_FULL, 1.8, 0.80, S1_FULL, "ledger"),
    (0.92, 0.9, -0.50, 0.12, "rest_crud_easy"),
    (0.45, 2.0, 0.50, 0.10, "rate_limiter_trap"),
    (0.68, 1.5, 0.60, 0.11, "search_index"),
    (0.40, 1.6, 1.20, 0.13, "dist_log_hard"),
]


def _scalar_battery() -> list[ItemObservation]:
    return [
        ItemObservation(L=ell, a=a, b=b, s=s, item_id=i) for ell, a, b, s, i in _BATTERY
    ]


def _md_battery_dim0(D: int) -> list[ItemObservationMD]:
    """The five oracle items lifted onto axis 0 of a D-dim battery."""
    return [
        dimension_observation(0, ell, a, b, s, D, item_id=i)
        for ell, a, b, s, i in _BATTERY
    ]


# --- 1-D MD reduces to the scalar oracle exactly -----------------------------

def test_md_reduces_to_scalar():
    cfg = resolve_config(None)

    # dimension_observation on D=1 sets b_MD = a * b_scalar, so the 1-D MD item
    # model g = sigmoid(a*theta - a*b) = sigmoid(a(theta - b)) matches the scalar.
    for ell, a, b, s, _ in _BATTERY:
        obs = dimension_observation(0, ell, a, b, s, 1)
        assert obs.a_vec == (a,)
        assert obs.b == a * b  # b_MD = a * b_scalar

    est_md = fit_ability_md(_md_battery_dim0(1), cfg, dims=1)
    est_scalar = fit_ability(_scalar_battery(), cfg)

    # 1-D MD reproduces the scalar oracle to <=1e-6 (both hit the same grad=0
    # root; the MD Fisher-scoring line search settles at the float-flat optimum a
    # few 1e-9 from the analytic root, far inside the 1e-3 acceptance tolerance).
    assert abs(est_md.theta_hat[0] - ORACLE_THETA) <= 1e-6
    assert abs(est_md.theta_hat[0] - est_scalar.theta_hat) <= 1e-6
    assert abs(est_md.information[0][0] - ORACLE_INFO) <= 1e-6
    assert abs(est_md.information[0][0] - est_scalar.information) <= 1e-6
    assert abs(est_md.se[0] - ORACLE_SE) <= 1e-6
    assert abs(est_md.se[0] - est_scalar.se) <= 1e-6

    # Per-item information (trace of each item's DxD contribution) matches the
    # scalar per-item Fisher information for the 1-D reduction.
    assert len(est_md.per_item_information) == 5
    for got, want in zip(
        est_md.per_item_information, est_scalar.per_item_information, strict=True
    ):
        assert abs(got - want) <= 1e-6

    assert est_md.converged
    assert est_md.dims == ("dec",)


# --- Fisher matrix is symmetric positive-definite ----------------------------

def test_fisher_symmetric_positive_definite():
    cfg = resolve_config(None)
    est = fit_ability_md(_md_battery_dim0(5), cfg, dims=5)

    info = np.asarray(est.information, dtype=np.float64)
    assert info.shape == (5, 5)
    # Symmetric.
    assert np.allclose(info, info.T, atol=1e-12)
    # Positive definite: all eigenvalues strictly positive.
    eigvals = np.linalg.eigvalsh(info)
    assert float(np.min(eigvals)) > 0.0
    # Unobserved dimensions keep the prior information 1/tau2 on the diagonal.
    assert abs(info[1][1] - 1.0 / cfg.irt.tau2) <= 1e-9


# --- per-dim SE is the diagonal of I^-1 --------------------------------------

def test_se_is_diag_of_inverse_information():
    cfg = resolve_config(None)
    est = fit_ability_md(_md_battery_dim0(5), cfg, dims=5)

    info = np.asarray(est.information, dtype=np.float64)
    cov = np.linalg.inv(info)
    for d in range(5):
        assert abs(est.se[d] - float(np.sqrt(cov[d][d]))) <= 1e-6


# --- objective process signal on the ver axis --------------------------------

def test_ver_process_signal_raises_theta_and_shrinks_se():
    cfg = resolve_config(None)
    ver = cfg.irt.dims.index("ver")  # index 1

    base = _md_battery_dim0(5)
    est_base = fit_ability_md(base, cfg, dims=5)
    # No observation loads the ver axis -> prior mean 0, prior SE sqrt(tau2).
    assert abs(est_base.theta_hat[ver]) <= 1e-9
    assert abs(est_base.se[ver] - float(np.sqrt(cfg.irt.tau2))) <= 1e-6

    # A one-hot verification-rigor signal on the ver axis: high L pushes theta up.
    signal = dimension_observation(ver, 0.9, 1.5, 0.0, 0.10, 5, item_id="ver_signal")
    est_signal = fit_ability_md([*base, signal], cfg, dims=5)

    assert est_signal.theta_hat[ver] > est_base.theta_hat[ver]  # raised
    assert est_signal.se[ver] < est_base.se[ver]                # shrunk
    # The observed (dec) axis is essentially unchanged by an orthogonal signal.
    assert abs(est_signal.theta_hat[0] - est_base.theta_hat[0]) <= 1e-6


# --- empty battery -> prior ---------------------------------------------------

def test_empty_battery_returns_prior():
    cfg = resolve_config(None)
    est = fit_ability_md([], cfg, dims=5)

    assert est.theta_hat == tuple([cfg.irt.init_theta] * 5)
    assert est.iterations == 0
    assert est.converged
    assert est.per_item_information == []
    info = np.asarray(est.information, dtype=np.float64)
    assert np.allclose(info, np.eye(5) / cfg.irt.tau2)
    for d in range(5):
        assert abs(est.se[d] - float(np.sqrt(cfg.irt.tau2))) <= 1e-6


# --- item_information_md is rank-1 and peaks at the linear-predictor root -----

def test_item_information_md_rank_one():
    a_vec = np.array([1.4, 0.0, 0.0], dtype=np.float64)
    # g = sigmoid(a_vec . theta - b); at the root a_vec.theta = b, g = 0.5, h max.
    theta_peak = np.array([0.5, 0.0, 0.0], dtype=np.float64)  # a*theta0 = 1.4*0.5 = 0.7 = b
    info = item_information_md(theta_peak, a_vec, 0.7, 0.10)
    assert info.shape == (3, 3)
    assert np.allclose(info, info.T)
    # Rank 1: exactly one non-zero eigenvalue.
    eigvals = np.sort(np.abs(np.linalg.eigvalsh(info)))
    assert eigvals[0] <= 1e-9 and eigvals[1] <= 1e-9
    assert eigvals[2] > 0.0
    # h(=g(1-g)) is maximal at g=0.5, so info[0][0] peaks at theta_peak.
    off = item_information_md(np.array([1.5, 0.0, 0.0]), a_vec, 0.7, 0.10)
    assert info[0][0] >= off[0][0]


# --- D-optimal CAT selection --------------------------------------------------

def test_select_next_item_md_d_optimal():
    cfg = resolve_config(None)
    battery = _md_battery_dim0(5)
    est = fit_ability_md(battery, cfg, dims=5)
    theta = np.asarray(est.theta_hat, dtype=np.float64)
    fisher = np.asarray(est.information, dtype=np.float64)

    # A candidate that loads an unobserved (ver) axis maximizes log det gain.
    ver_cand = dimension_observation(1, 0.7, 1.6, 0.0, 0.10, 5, item_id="ver_cand")
    dec_cand = dimension_observation(0, 0.7, 1.6, 0.0, 0.10, 5, item_id="dec_cand")
    chosen = select_next_item_md(theta, fisher, [dec_cand, ver_cand], set())
    assert chosen is not None
    assert chosen.item_id == "ver_cand"

    # None when every candidate is used.
    used = {"dec_cand", "ver_cand"}
    assert select_next_item_md(theta, fisher, [dec_cand, ver_cand], used) is None


# --- validation ---------------------------------------------------------------

def test_item_observation_md_rejects_bad_params():
    import pytest

    with pytest.raises(ValueError):
        ItemObservationMD(L=0.5, a_vec=(1.0,), b=0.0, s=0.0)      # s must be > 0
    with pytest.raises(ValueError):
        ItemObservationMD(L=0.5, a_vec=(), b=0.0, s=0.1)          # a_vec non-empty
    with pytest.raises(ValueError):
        ItemObservationMD(L=0.5, a_vec=(0.0, 0.0), b=0.0, s=0.1)  # a_vec any nonzero
    with pytest.raises(ValueError):
        dimension_observation(5, 0.5, 1.0, 0.0, 0.1, 5)           # dim out of range


def test_to_json_rounds_display_only():
    cfg = resolve_config(None)
    est = fit_ability_md(_md_battery_dim0(1), cfg, dims=1)
    js = est.to_json(decimals=4)
    assert js["theta_hat"][0] == round(est.theta_hat[0], 4)
    assert js["se"][0] == round(est.se[0], 4)
    assert js["information"][0][0] == round(est.information[0][0], 4)
    assert js["dims"] == ["dec"]
    # Attribute stays full precision; only the serialized view is rounded.
    assert isinstance(est, AbilityEstimateMD)
    assert est.information[0][0] != js["information"][0][0]
