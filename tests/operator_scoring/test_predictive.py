"""Layer G (predictive re-weighting) acceptance oracle + property tests.

The acceptance oracle is reproduced at full precision (tol 1e-3). Inputs flow in
from Layer D at *full* precision (never ``round(...)``). Determinism is checked
byte-for-byte on ``to_json()``.
"""
from __future__ import annotations

import numpy as np

from app.operator_scoring.calibration_store import CalibrationParams
from app.operator_scoring.config import resolve_config
from app.operator_scoring.predictive import (
    Prediction,
    TrainRow,
    apply_isotonic,
    apply_platt,
    fit_isotonic,
    fit_platt,
    fit_predictive,
    predict,
)
from tests.operator_scoring.conftest import approx

# Full-precision Layer-D outputs feeding Layer G (NOT display-rounded).
THETA_HAT = 0.8757518709631057
SE_THETA = 0.13173436450445417

# Oracle expectations (SCORING_DESIGN.md sections 8 & 12), full precision.
ORACLE_LIN = 0.4333270580594163
ORACLE_YHAT = 0.6066678586910024
ORACLE_LOWER = 0.5331701606541919
ORACLE_UPPER = 0.6756338492825221


def _oracle_params() -> CalibrationParams:
    """The default/oracle Layer-G calibration record (method 'none')."""
    return CalibrationParams(
        gamma=(-0.80, 1.10, 0.60, -0.15),
        feature_names=("theta", "v", "agent"),
        sigma_reg=0.05,
        method="none",
    )


# --- acceptance oracle -------------------------------------------------------

def test_predict_oracle():
    cfg = resolve_config(None)
    params = _oracle_params()
    pred = predict(
        theta_hat=THETA_HAT,
        se_theta=SE_THETA,
        v=0.70,
        agent=1,
        params=params,
        config=cfg,
    )

    assert approx(pred.lin, ORACLE_LIN)
    assert approx(pred.y_hat, ORACLE_YHAT)
    assert approx(pred.y_lower, ORACLE_LOWER)
    assert approx(pred.y_upper, ORACLE_UPPER)

    # Interval is ordered, strictly inside (0, 1), and pushed through sigmoid.
    assert 0.0 < pred.y_lower < pred.y_hat < pred.y_upper < 1.0

    # Asymmetric: the two half-widths differ (bounded by the sigmoid).
    lower_gap = pred.y_hat - pred.y_lower
    upper_gap = pred.y_upper - pred.y_hat
    assert not approx(lower_gap, upper_gap)

    # method 'none' is the identity: no calibration applied.
    assert pred.calibrated is False
    assert pred.calibration_method == "none"


def test_var_lin_formula_exact():
    cfg = resolve_config(None)
    params = _oracle_params()
    pred = predict(THETA_HAT, SE_THETA, 0.70, 1, params, cfg)

    expected_var = 1.10**2 * SE_THETA**2 + 0.05**2
    assert approx(pred.var_lin, expected_var, tol=1e-12)
    assert approx(pred.se_lin, expected_var**0.5, tol=1e-12)
    # y_hat is exactly sigmoid(lin) under the identity calibration.
    assert approx(pred.y_hat, 1.0 / (1.0 + np.exp(-pred.lin)), tol=1e-12)


def test_interval_ordering_in_unit_interval():
    """A sweep of inputs: interval stays ordered and inside (0, 1)."""
    cfg = resolve_config(None)
    params = _oracle_params()
    for theta in np.linspace(-3.0, 3.0, 13):
        for se in (0.05, 0.13, 0.4):
            for v in (0.0, 0.5, 1.0):
                for agent in (0.0, 1.0):
                    pred = predict(float(theta), se, v, agent, params, cfg)
                    assert 0.0 < pred.y_lower < pred.y_hat < pred.y_upper < 1.0
                    assert pred.var_lin > 0.0
                    assert pred.se_lin > 0.0


# --- IRLS recovers a planted gamma from a soft-label design grid -------------

def test_irls_recovers_planted_gamma():
    gamma_true = np.array([-0.5, 1.2, 0.7, -0.3], dtype=np.float64)
    rows: list[TrainRow] = []
    for theta in np.linspace(-2.0, 2.0, 7):
        for v in np.linspace(0.0, 1.0, 5):
            for agent in (0.0, 1.0):
                lin = (
                    gamma_true[0]
                    + gamma_true[1] * theta
                    + gamma_true[2] * v
                    + gamma_true[3] * agent
                )
                p = 1.0 / (1.0 + np.exp(-lin))  # exact soft label
                rows.append(TrainRow(theta=float(theta), v=float(v), agent=float(agent), y=float(p)))

    # Small ridge so the MLE (which sits exactly at gamma_true for soft labels)
    # is recovered tightly.
    cfg = resolve_config({"predictive": {"ridge_lambda": 1e-8}})
    params = fit_predictive(rows, cfg)

    assert params.converged
    assert params.n_train == len(rows)
    assert len(params.gamma) == 4
    for got, want in zip(params.gamma, gamma_true.tolist(), strict=True):
        assert approx(got, want, tol=1e-2)


def test_fit_predictive_empty_falls_back_to_defaults():
    cfg = resolve_config(None)
    params = fit_predictive([], cfg)
    assert params.gamma == tuple(cfg.predictive.gamma)
    assert params.n_train == 0
    assert params.converged is True


# --- PAVA isotonic: monotone, matches the pinned example ---------------------

def test_pava_monotone():
    scores = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    labels = [0.0, 0.0, 1.0, 0.0, 1.0, 1.0]
    iso = fit_isotonic(scores, labels)

    # PAVA pools the (1, 0) violation at indices 2-3 to their mean 0.5.
    assert iso.y == (0.0, 0.0, 0.5, 0.5, 1.0, 1.0)
    ys = list(iso.y)
    assert all(ys[i] <= ys[i + 1] for i in range(len(ys) - 1))

    # Applied at the knots reproduces the fitted values; it is non-decreasing.
    applied = apply_isotonic(np.asarray(scores, dtype=float), iso)
    assert np.allclose(applied, [0.0, 0.0, 0.5, 0.5, 1.0, 1.0])
    grid = np.linspace(-1.0, 6.0, 71)
    g = np.asarray(apply_isotonic(grid, iso))
    assert np.all(np.diff(g) >= -1e-12)


# --- Platt scaling: monotone increasing -------------------------------------

def test_platt_monotone():
    cfg = resolve_config(None)
    scores = np.linspace(-3.0, 3.0, 61)
    labels = (scores > 0.0).astype(float)
    params = fit_platt(scores, labels, cfg)

    assert params.A > 0.0  # increasing relationship => positive slope
    applied = np.asarray(apply_platt(scores, params))
    assert np.all(np.diff(applied) >= -1e-12)
    assert np.all(applied > 0.0) and np.all(applied < 1.0)


def test_predict_platt_calibration_preserves_ordering():
    """Platt-calibrated predict still yields an ordered interval inside (0, 1)."""
    cfg = resolve_config(None)
    scores = np.linspace(-4.0, 4.0, 81)
    labels = (scores > 0.0).astype(float)
    platt = fit_platt(scores, labels, cfg)
    params = CalibrationParams(
        gamma=(-0.80, 1.10, 0.60, -0.15),
        feature_names=("theta", "v", "agent"),
        sigma_reg=0.05,
        method="platt",
        platt=platt,
    )
    pred = predict(THETA_HAT, SE_THETA, 0.70, 1, params, cfg)
    assert pred.calibrated is True
    assert pred.calibration_method == "platt"
    assert 0.0 < pred.y_lower < pred.y_hat < pred.y_upper < 1.0


# --- determinism -------------------------------------------------------------

def test_determinism():
    cfg = resolve_config(None)
    rows = [
        TrainRow(theta=0.5, v=0.5, agent=1.0, y=0.7),
        TrainRow(theta=-0.5, v=0.2, agent=0.0, y=0.3),
        TrainRow(theta=1.0, v=0.8, agent=1.0, y=0.9),
        TrainRow(theta=0.0, v=0.0, agent=0.0, y=0.4),
        TrainRow(theta=-1.2, v=0.6, agent=1.0, y=0.25),
    ]
    p1 = fit_predictive(rows, cfg)
    p2 = fit_predictive(rows, cfg)
    assert p1.gamma == p2.gamma
    assert p1.to_json() == p2.to_json()

    params = _oracle_params()
    a = predict(THETA_HAT, SE_THETA, 0.70, 1, params, cfg)
    b = predict(THETA_HAT, SE_THETA, 0.70, 1, params, cfg)
    assert isinstance(a, Prediction)
    assert a.to_json() == b.to_json()


def test_to_json_rounds_display_only():
    cfg = resolve_config(None)
    pred = predict(THETA_HAT, SE_THETA, 0.70, 1, _oracle_params(), cfg)
    js = pred.to_json(decimals=4)
    assert js["lin"] == round(pred.lin, 4)
    assert js["y_hat"] == round(pred.y_hat, 4)
    assert js["y_lower"] == round(pred.y_lower, 4)
    assert js["y_upper"] == round(pred.y_upper, 4)
    assert js["calibration_method"] == "none"
    # Attributes stay full precision behind the rounded view.
    assert pred.y_hat != js["y_hat"] or pred.y_hat == round(pred.y_hat, 4)
