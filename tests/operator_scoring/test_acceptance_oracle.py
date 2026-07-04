"""Cross-cutting acceptance-oracle regression (SCORING_DESIGN.md sections 12).

This threads the four layers end-to-end at **full precision** by calling the real
modules -- ``grade_outcome`` (B), ``compute_lift`` (E), ``fit_ability`` (D) and
``predict`` (G) -- and asserts *every* pinned oracle value from section 12 in a
single table (tol 1e-3). Full precision is load-bearing at the E -> D boundary:
:func:`test_full_precision_flow_required` shows that feeding the display-rounded
``L1``/``s1`` through an unguarded Newton (Layer D stripped of its guard + line
search) lands in the wrong basin (``|theta - 0.8758| > 1.0``), while the guarded
solver on the full-precision battery reproduces the oracle.
"""
from __future__ import annotations

import numpy as np

from app.operator_scoring.calibration_store import CalibrationParams
from app.operator_scoring.config import OperatorScoringConfig, resolve_config
from app.operator_scoring.grader import StaticRunner, SubCheck, grade_outcome
from app.operator_scoring.irt import ItemObservation, fit_ability, select_next_item
from app.operator_scoring.lift import BaselineStats, compute_lift
from app.operator_scoring.predictive import predict
from tests.operator_scoring.conftest import approx

# --- oracle inputs (SCORING_DESIGN.md section 12) ----------------------------

# Layer B: five weighted hidden sub-checks. ``name`` is descriptive; ``kind`` is
# the allowed-kind tag validated by the grader. StaticRunner returns each
# check's ``result`` so the graded outcome is deterministic (R = 1 => phi = 0).
_B_CHECKS: list[SubCheck] = [
    SubCheck(name="functional_core", kind="functional", weight=0.35, result=1.0),
    SubCheck(name="edge_adversarial", kind="edge_adversarial", weight=0.35, result=0.7),
    SubCheck(name="property_invariants", kind="property_invariants", weight=0.15, result=1.0),
    SubCheck(name="performance", kind="performance", weight=0.10, result=0.5),
    SubCheck(name="security_fuzz", kind="security_fuzz", weight=0.05, result=1.0),
]

# Layer E baseline / anchoring for the ledger item.
_BASELINE = BaselineStats(mu0=0.55, sigma0=0.08, M=20)
_CEILING = 0.97
_SIGMA_INTRINSIC = 0.10

# Layer G covariates + the default/oracle calibration record (method "none").
_V = 0.70
_AGENT = 1.0


def _oracle_params() -> CalibrationParams:
    return CalibrationParams(
        gamma=(-0.80, 1.10, 0.60, -0.15),
        feature_names=("theta", "v", "agent"),
        sigma_reg=0.05,
        method="none",
    )


# --- full-precision expectations (SCORING_DESIGN.md section 12) ---------------

ORACLE_O1 = 0.845
ORACLE_WEIGHT_SUM = 1.0
ORACLE_L1 = 0.7023809523809523
ORACLE_S1 = 0.10869249724298408
ORACLE_THETA = 0.8757518709631057
ORACLE_INFO = 57.62379258827583
ORACLE_SE = 0.13173436450445417
ORACLE_CI = (0.6175525, 1.1339512)
ORACLE_PER_ITEM = [16.982114, 1.707714, 18.970816, 10.675488, 8.287660]
ORACLE_CAT_ARGMAX = "rate_limiter_trap"
ORACLE_LIN = 0.4333270580594163
ORACLE_YHAT = 0.6066678586910024
ORACLE_INTERVAL = (0.5331702, 0.6756338)


def _battery(l1: float, s1: float) -> list[ItemObservation]:
    """The five-item acceptance battery (order is load-bearing for per-item info)."""
    return [
        ItemObservation(L=l1, a=1.8, b=0.80, s=s1, item_id="ledger"),
        ItemObservation(L=0.92, a=0.9, b=-0.50, s=0.12, item_id="rest_crud_easy"),
        ItemObservation(L=0.45, a=2.0, b=0.50, s=0.10, item_id="rate_limiter_trap"),
        ItemObservation(L=0.68, a=1.5, b=0.60, s=0.11, item_id="search_index"),
        ItemObservation(L=0.40, a=1.6, b=1.20, s=0.13, item_id="dist_log_hard"),
    ]


def _thread_full_precision() -> tuple[object, object, object, object, list[ItemObservation]]:
    """Thread B -> E -> D -> G at full precision by calling the real modules."""
    cfg = resolve_config(None)
    rng = np.random.default_rng(0)

    grade = grade_outcome(_B_CHECKS, StaticRunner(), cfg.grader, rng, replays=1)
    lift = compute_lift(grade.outcome, _BASELINE, _CEILING, _SIGMA_INTRINSIC, cfg)
    # ItemObservation is built from the FULL-precision LiftResult.L / .s (never
    # round(...)); the other four items carry their fixed calibration.
    battery = [
        ItemObservation(L=lift.L, a=1.8, b=0.80, s=lift.s, item_id="ledger"),
        ItemObservation(L=0.92, a=0.9, b=-0.50, s=0.12, item_id="rest_crud_easy"),
        ItemObservation(L=0.45, a=2.0, b=0.50, s=0.10, item_id="rate_limiter_trap"),
        ItemObservation(L=0.68, a=1.5, b=0.60, s=0.11, item_id="search_index"),
        ItemObservation(L=0.40, a=1.6, b=1.20, s=0.13, item_id="dist_log_hard"),
    ]
    est = fit_ability(battery, cfg)
    pred = predict(est.theta_hat, est.se, _V, _AGENT, _oracle_params(), cfg)
    return grade, lift, est, pred, battery


# --- table-driven regression over every section-12 oracle value --------------

def test_acceptance_oracle_full_precision_thread():
    grade, lift, est, pred, battery = _thread_full_precision()

    table: list[tuple[str, float, float]] = [
        ("B.weight_sum", grade.weight_sum, ORACLE_WEIGHT_SUM),
        ("B.O1", grade.outcome, ORACLE_O1),
        ("E.L1", lift.L, ORACLE_L1),
        ("E.s1", lift.s, ORACLE_S1),
        ("D.theta_hat", est.theta_hat, ORACLE_THETA),
        ("D.information", est.information, ORACLE_INFO),
        ("D.se", est.se, ORACLE_SE),
        ("D.ci_low", est.ci95[0], ORACLE_CI[0]),
        ("D.ci_high", est.ci95[1], ORACLE_CI[1]),
        ("G.lin", pred.lin, ORACLE_LIN),
        ("G.y_hat", pred.y_hat, ORACLE_YHAT),
        ("G.y_lower", pred.y_lower, ORACLE_INTERVAL[0]),
        ("G.y_upper", pred.y_upper, ORACLE_INTERVAL[1]),
    ]
    for name, actual, expected in table:
        assert approx(actual, expected), f"{name}: {actual!r} != {expected!r}"

    # D: per-item information (order matters).
    assert len(est.per_item_information) == len(ORACLE_PER_ITEM)
    for got, want in zip(est.per_item_information, ORACLE_PER_ITEM, strict=True):
        assert approx(got, want), f"per-item info {got!r} != {want!r}"

    # D: CAT next item is the most-informative unused item at theta_hat.
    assert est.next_item_id == ORACLE_CAT_ARGMAX
    chosen = select_next_item(est.theta_hat, battery, set())
    assert chosen is not None
    assert chosen.item_id == ORACLE_CAT_ARGMAX

    # G: interval is ordered, strictly inside (0, 1), and asymmetric (pushed
    # through the sigmoid so the two half-widths differ).
    assert 0.0 < pred.y_lower < pred.y_hat < pred.y_upper < 1.0
    lower_gap = pred.y_hat - pred.y_lower
    upper_gap = pred.y_upper - pred.y_hat
    assert not approx(lower_gap, upper_gap), "interval unexpectedly symmetric"

    # B: exactly five checks graded, deterministic path (single replay).
    assert grade.replays == 1
    assert grade.deterministic
    assert len(grade.checks) == 5


def test_layer_b_outcome_and_weight_sum():
    cfg = resolve_config(None)
    rng = np.random.default_rng(0)
    grade = grade_outcome(_B_CHECKS, StaticRunner(), cfg.grader, rng, replays=1)
    assert approx(grade.weight_sum, ORACLE_WEIGHT_SUM)
    assert approx(grade.outcome, ORACLE_O1)
    assert approx(grade.flakiness, 0.0)


def test_layer_e_lift_and_sd():
    cfg = resolve_config(None)
    lift = compute_lift(ORACLE_O1, _BASELINE, _CEILING, _SIGMA_INTRINSIC, cfg)
    assert approx(lift.L, ORACLE_L1)
    assert approx(lift.s, ORACLE_S1)
    assert lift.ceiling_degenerate is False


def test_layer_d_ability_from_full_precision_lift():
    cfg = resolve_config(None)
    est = fit_ability(_battery(ORACLE_L1, ORACLE_S1), cfg)
    assert approx(est.theta_hat, ORACLE_THETA)
    assert approx(est.information, ORACLE_INFO)
    assert approx(est.se, ORACLE_SE)
    assert approx(est.ci95[0], ORACLE_CI[0])
    assert approx(est.ci95[1], ORACLE_CI[1])
    for got, want in zip(est.per_item_information, ORACLE_PER_ITEM, strict=True):
        assert approx(got, want)
    assert est.next_item_id == ORACLE_CAT_ARGMAX
    assert est.n_items == 5
    assert est.converged


def test_layer_g_prediction_from_full_precision_ability():
    cfg = resolve_config(None)
    pred = predict(ORACLE_THETA, ORACLE_SE, _V, _AGENT, _oracle_params(), cfg)
    assert approx(pred.lin, ORACLE_LIN)
    assert approx(pred.y_hat, ORACLE_YHAT)
    assert approx(pred.y_lower, ORACLE_INTERVAL[0])
    assert approx(pred.y_upper, ORACLE_INTERVAL[1])
    assert 0.0 < pred.y_lower < pred.y_hat < pred.y_upper < 1.0


# --- full precision is load-bearing at the E -> D boundary -------------------

def _naive_newton(
    observations: list[ItemObservation],
    config: OperatorScoringConfig,
    max_iter: int = 100,
) -> float:
    """Raw observed-Hessian Newton with no ``-Fisher`` guard and no line search.

    This is Layer D stripped of the guarded-solver machinery ``fit_ability``
    provides. On the display-rounded battery it overshoots the unique interior
    optimum and diverges to the theta-bound region; the exact corrupted value is
    numpy-build dependent, so the caller asserts a threshold, not a pinned value.
    """
    irt = config.irt
    tau2 = irt.tau2
    lo, hi = irt.theta_bounds
    arr_l = np.array([o.L for o in observations], dtype=np.float64)
    arr_a = np.array([o.a for o in observations], dtype=np.float64)
    arr_b = np.array([o.b for o in observations], dtype=np.float64)
    arr_s = np.array([o.s for o in observations], dtype=np.float64)
    theta = float(irt.init_theta)
    for _ in range(max_iter):
        g = 1.0 / (1.0 + np.exp(-(arr_a * (theta - arr_b))))
        gp = arr_a * g * (1.0 - g)
        gpp = arr_a * arr_a * g * (1.0 - g) * (1.0 - 2.0 * g)
        grad = float(-theta / tau2 + np.sum((arr_l - g) * gp / arr_s**2))
        hess = float(-1.0 / tau2 + np.sum((-(gp**2) + (arr_l - g) * gpp) / arr_s**2))
        theta = min(hi, max(lo, theta - grad / hess))
        if abs(grad) < irt.grad_tol:
            break
    return float(theta)


def test_full_precision_flow_required():
    """Rounding at the E -> D boundary breaks the estimate.

    The guarded solver on the full-precision battery reproduces the oracle; the
    unguarded Newton on the display-rounded ``L1``/``s1`` diverges by more than
    ``1.0`` from ``theta = 0.8758``.
    """
    cfg = resolve_config(None)

    est_full = fit_ability(_battery(ORACLE_L1, ORACLE_S1), cfg)
    assert approx(est_full.theta_hat, ORACLE_THETA)

    l1_round = round(ORACLE_L1, 4)   # 0.7024
    s1_round = round(ORACLE_S1, 4)   # 0.1087
    theta_rounded = _naive_newton(_battery(l1_round, s1_round), cfg)
    assert abs(theta_rounded - 0.8758) > 1.0, (
        f"rounded L1/s1 did not diverge: theta={theta_rounded!r}"
    )
