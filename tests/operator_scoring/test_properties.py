"""Property invariants for the operator scoring core (SCORING_DESIGN.md section 13).

These are deterministic property tests driven by ``conftest.given_seeded`` (a
single seeded ``numpy.random.Generator``); there is **no** hypothesis dependency.
Each test draws a bounded, realistic sample so Newton always converges
(``a in [0.5, 2.5]``, ``b in [-2, 2]``, ``s in [0.05, 0.2]``, ``L in [-0.2, 1.2]``)
and prints the offending case on failure.

Invariants covered:

1. ``L`` strictly increasing in ``O`` (``dL/dO = 1/denom > 0``).
2. ``theta_hat`` non-decreasing when any single ``L_i`` rises.
3. Fisher SE strictly shrinks when an ``a != 0`` item is added (``I`` is
   ``1/tau2 + sum`` of non-negative per-item terms, evaluated at a fixed theta).
4. Single-item information peaks at ``theta = b_i``.
5. ``O`` strictly increasing in each ``c_k`` with ``w_k > 0``.
6. ``Y_hat`` monotone in ``theta_hat`` in the direction of ``sign(gamma1)``.
7. ``L`` is unclipped (``O < mu0 => L < 0``).
8. The prediction interval is ordered and strictly inside ``(0, 1)``.
"""
from __future__ import annotations

import numpy as np

from app.operator_scoring.calibration_store import CalibrationParams
from app.operator_scoring.config import resolve_config
from app.operator_scoring.grader import StaticRunner, SubCheck, grade_outcome
from app.operator_scoring.irt import ItemObservation, fit_ability, item_information
from app.operator_scoring.lift import BaselineStats, compute_lift
from app.operator_scoring.predictive import predict
from tests.operator_scoring.conftest import DEFAULT_SEED, given_seeded

CFG = resolve_config(None)
_N = 200

# Allowed sub-check kinds (mirror GraderConfig.allowed_kinds) for property 5.
_KINDS = ("functional", "edge_adversarial", "property_invariants", "performance", "security_fuzz")


def _oracle_params() -> CalibrationParams:
    return CalibrationParams(
        gamma=(-0.80, 1.10, 0.60, -0.15),
        feature_names=("theta", "v", "agent"),
        sigma_reg=0.05,
        method="none",
    )


# --- 1. L strictly increasing in O -------------------------------------------

def _sample_lift_pair(rng: np.random.Generator) -> dict:
    mu0 = float(rng.uniform(0.2, 0.6))
    ceiling = mu0 + float(rng.uniform(0.2, 0.39))  # positive gap, ceiling <= 0.99
    sigma0 = float(rng.uniform(0.02, 0.15))
    m = int(rng.integers(5, 31))
    o_lo = float(rng.uniform(0.0, 0.5))
    o_hi = o_lo + float(rng.uniform(0.02, 0.4))
    return {
        "baseline": BaselineStats(mu0=mu0, sigma0=sigma0, M=m),
        "ceiling": ceiling,
        "o_lo": o_lo,
        "o_hi": o_hi,
    }


def test_property_L_monotone_in_O():
    for case in given_seeded(_N, _sample_lift_pair, seed=DEFAULT_SEED):
        lo = compute_lift(case["o_lo"], case["baseline"], case["ceiling"], 0.10, CFG)
        hi = compute_lift(case["o_hi"], case["baseline"], case["ceiling"], 0.10, CFG)
        assert hi.L > lo.L, f"L not increasing in O: {case} -> {lo.L} !< {hi.L}"


# --- 2. theta_hat non-decreasing when any single L_i rises -------------------

def _draw_item(rng: np.random.Generator, item_id: str) -> ItemObservation:
    return ItemObservation(
        L=float(rng.uniform(-0.2, 1.2)),
        a=float(rng.uniform(0.5, 2.5)),
        b=float(rng.uniform(-2.0, 2.0)),
        s=float(rng.uniform(0.05, 0.2)),
        item_id=item_id,
    )


def _sample_bump_case(rng: np.random.Generator) -> dict:
    n = int(rng.integers(2, 6))
    battery = [_draw_item(rng, f"it{k}") for k in range(n)]
    idx = int(rng.integers(0, n))
    delta = float(rng.uniform(0.05, 0.3))
    return {"battery": battery, "idx": idx, "delta": delta}


def test_property_theta_nondecreasing_in_L():
    for case in given_seeded(_N, _sample_bump_case, seed=DEFAULT_SEED):
        battery = case["battery"]
        theta0 = fit_ability(battery, CFG).theta_hat
        item = battery[case["idx"]]
        bumped = list(battery)
        bumped[case["idx"]] = ItemObservation(
            L=item.L + case["delta"], a=item.a, b=item.b, s=item.s, item_id=item.item_id
        )
        theta1 = fit_ability(bumped, CFG).theta_hat
        # Strict for a_i > 0 (d grad / d L_i = g_i'/s_i^2 > 0); allow float slack.
        assert theta1 >= theta0 - 1e-9, f"theta decreased on L bump: {theta0} -> {theta1} ({case})"


# --- 3. Fisher SE strictly shrinks when an a != 0 item is added --------------

def _sample_add_case(rng: np.random.Generator) -> dict:
    theta = float(rng.uniform(-2.0, 2.0))
    n = int(rng.integers(1, 5))
    battery = [_draw_item(rng, f"it{k}") for k in range(n)]
    extra = _draw_item(rng, "extra")
    return {"theta": theta, "battery": battery, "extra": extra}


def test_property_se_shrinks_on_add():
    tau2 = CFG.irt.tau2
    for case in given_seeded(_N, _sample_add_case, seed=DEFAULT_SEED):
        theta = case["theta"]
        info_before = 1.0 / tau2 + sum(
            item_information(theta, it.a, it.b, it.s) for it in case["battery"]
        )
        extra = case["extra"]
        info_after = info_before + item_information(theta, extra.a, extra.b, extra.s)
        se_before = 1.0 / np.sqrt(info_before)
        se_after = 1.0 / np.sqrt(info_after)
        assert se_after < se_before, f"SE did not shrink on add: {se_before} -> {se_after} ({case})"


# --- 4. single-item information peaks at theta = b ---------------------------

def _sample_info_item(rng: np.random.Generator) -> dict:
    return {
        "a": float(rng.uniform(0.5, 2.5)),
        "b": float(rng.uniform(-2.0, 2.0)),
        "s": float(rng.uniform(0.05, 0.2)),
    }


def test_property_information_peaks_at_b():
    for case in given_seeded(_N, _sample_info_item, seed=DEFAULT_SEED):
        a, b, s = case["a"], case["b"], case["s"]
        grid = np.linspace(b - 3.0, b + 3.0, 601)  # fine grid so argmax lands near b
        infos = [item_information(float(t), a, b, s) for t in grid]
        argmax_theta = float(grid[int(np.argmax(infos))])
        step = float(grid[1] - grid[0])
        assert abs(argmax_theta - b) <= step + 1e-9, (
            f"info peak {argmax_theta} not at b={b} ({case})"
        )


# --- 5. O strictly increasing in each c_k with w_k > 0 ----------------------

def _sample_grader_case(rng: np.random.Generator) -> dict:
    n = int(rng.integers(2, 6))
    checks = [
        SubCheck(
            name=f"c{k}",
            kind=_KINDS[k % len(_KINDS)],
            weight=float(rng.uniform(0.1, 1.0)),
            result=float(rng.uniform(0.0, 1.0)),
        )
        for k in range(n)
    ]
    target = int(rng.integers(0, n))
    c_lo = float(rng.uniform(0.0, 0.4))
    c_hi = c_lo + float(rng.uniform(0.2, 0.6))
    return {"checks": checks, "target": f"c{target}", "c_lo": c_lo, "c_hi": c_hi}


def test_property_O_monotone_in_each_c():
    rng = np.random.default_rng(0)  # StaticRunner ignores rng; grader draws nothing
    for case in given_seeded(_N, _sample_grader_case, seed=DEFAULT_SEED):
        checks = case["checks"]
        lo = grade_outcome(
            checks, StaticRunner(values={case["target"]: case["c_lo"]}), CFG.grader, rng, replays=1
        )
        hi = grade_outcome(
            checks, StaticRunner(values={case["target"]: case["c_hi"]}), CFG.grader, rng, replays=1
        )
        assert hi.outcome > lo.outcome, (
            f"O not increasing in c_target: {lo.outcome} !< {hi.outcome} ({case['target']})"
        )


# --- 6. Y_hat monotone in theta in the direction of sign(gamma1) ------------

def _sample_predict_pair(rng: np.random.Generator) -> dict:
    theta_lo = float(rng.uniform(-3.0, 2.0))
    theta_hi = theta_lo + float(rng.uniform(0.1, 1.0))
    return {
        "theta_lo": theta_lo,
        "theta_hi": theta_hi,
        "se": float(rng.uniform(0.05, 0.4)),
        "v": float(rng.uniform(0.0, 1.0)),
        "agent": float(rng.integers(0, 2)),
    }


def test_property_yhat_monotone_in_theta():
    params = _oracle_params()  # gamma1 = 1.10 > 0 => Y_hat increasing in theta
    for case in given_seeded(_N, _sample_predict_pair, seed=DEFAULT_SEED):
        lo = predict(case["theta_lo"], case["se"], case["v"], case["agent"], params, CFG)
        hi = predict(case["theta_hi"], case["se"], case["v"], case["agent"], params, CFG)
        assert hi.y_hat > lo.y_hat, f"Y_hat not increasing in theta: {lo.y_hat} !< {hi.y_hat} ({case})"


# --- 7. L is unclipped (O < mu0 => L < 0) -----------------------------------

def _sample_below_baseline(rng: np.random.Generator) -> dict:
    mu0 = float(rng.uniform(0.3, 0.7))
    ceiling = mu0 + float(rng.uniform(0.1, 0.29))
    sigma0 = float(rng.uniform(0.02, 0.15))
    m = int(rng.integers(5, 31))
    o = float(rng.uniform(0.0, mu0 - 0.05))  # strictly below the baseline mean
    return {"baseline": BaselineStats(mu0=mu0, sigma0=sigma0, M=m), "ceiling": ceiling, "o": o}


def test_property_L_unclipped_below_baseline():
    for case in given_seeded(_N, _sample_below_baseline, seed=DEFAULT_SEED):
        res = compute_lift(case["o"], case["baseline"], case["ceiling"], 0.10, CFG)
        assert res.L < 0.0, f"L clipped at/above 0 for O<mu0: {case} -> L={res.L}"


# --- 8. prediction interval ordered and strictly inside (0, 1) --------------

def _sample_interval_case(rng: np.random.Generator) -> dict:
    return {
        "theta": float(rng.uniform(-3.0, 3.0)),
        "se": float(rng.uniform(0.05, 0.4)),
        "v": float(rng.uniform(0.0, 1.0)),
        "agent": float(rng.integers(0, 2)),
    }


def test_property_interval_ordering_in_unit_interval():
    params = _oracle_params()
    for case in given_seeded(_N, _sample_interval_case, seed=DEFAULT_SEED):
        pred = predict(case["theta"], case["se"], case["v"], case["agent"], params, CFG)
        assert 0.0 < pred.y_lower < pred.y_hat < pred.y_upper < 1.0, (
            f"interval not ordered in (0, 1): "
            f"({pred.y_lower}, {pred.y_hat}, {pred.y_upper}) for {case}"
        )
        assert pred.var_lin > 0.0
        assert pred.se_lin > 0.0
