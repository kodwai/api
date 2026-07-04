"""Pipeline composition acceptance oracle + full-precision regression.

``run_pipeline`` wires Layers B -> E -> D -> G. This suite reproduces the full
end-to-end acceptance oracle (SCORING_DESIGN.md section 12) at full precision
(tol 1e-3), proves ``outcome_override`` bypasses the grader, and pins the
load-bearing full-precision invariant at the E -> D boundary: rounding the
current item's ``L``/``s`` drives the (unguarded) Newton solver into a wrong
basin, ``|theta - 0.8758| > 1``.
"""
from __future__ import annotations

import numpy as np

from app.operator_scoring.config import OperatorScoringConfig, resolve_config
from app.operator_scoring.grader import SubCheck
from app.operator_scoring.irt import ItemObservation
from app.operator_scoring.lift import BaselineStats
from app.operator_scoring.numerics import SeededRNG
from app.operator_scoring.pipeline import (
    PipelineInputs,
    PipelineResult,
    run_pipeline,
)
from tests.operator_scoring.conftest import approx

# --- oracle expectations (SCORING_DESIGN.md sections 5-8 & 12), full precision --
ORACLE_O1 = 0.845
ORACLE_L1 = 0.7023809523809523
ORACLE_S1 = 0.10869249724298408
ORACLE_THETA = 0.8757518709631057
ORACLE_SE = 0.13173436450445417
ORACLE_LIN = 0.4333270580594163
ORACLE_YHAT = 0.6066678586910024
ORACLE_LOWER = 0.5331701606541919
ORACLE_UPPER = 0.6756338492825221


def _oracle_checks() -> list[SubCheck]:
    """The five weighted Layer-B sub-checks; sum(weight) == 1.0 exactly."""
    return [
        SubCheck("functional_core", "functional", 0.35, 1.0),
        SubCheck("edge_adversarial", "edge_adversarial", 0.35, 0.7),
        SubCheck("property_invariants", "property_invariants", 0.15, 1.0),
        SubCheck("performance", "performance", 0.10, 0.5),
        SubCheck("security_fuzz", "security_fuzz", 0.05, 1.0),
    ]


def _oracle_history() -> list[ItemObservation]:
    """The four non-current battery items (order load-bearing for per-item info)."""
    return [
        ItemObservation(L=0.92, a=0.9, b=-0.50, s=0.12, item_id="rest_crud_easy"),
        ItemObservation(L=0.45, a=2.0, b=0.50, s=0.10, item_id="rate_limiter_trap"),
        ItemObservation(L=0.68, a=1.5, b=0.60, s=0.11, item_id="search_index"),
        ItemObservation(L=0.40, a=1.6, b=1.20, s=0.13, item_id="dist_log_hard"),
    ]


def _oracle_inputs(**overrides: object) -> PipelineInputs:
    """Assemble the full acceptance-oracle pipeline inputs (ledger is current)."""
    kwargs: dict[str, object] = {
        "checks": _oracle_checks(),
        "current_a": 1.8,
        "current_b": 0.80,
        "baseline": BaselineStats(0.55, 0.08, 20),
        "ceiling": 0.97,
        "sigma_intrinsic": 0.10,
        "history": _oracle_history(),
        "v": 0.70,
        "agent": 1,
    }
    kwargs.update(overrides)
    return PipelineInputs(**kwargs)  # type: ignore[arg-type]


def _naive_newton(
    observations: list[ItemObservation],
    config: OperatorScoringConfig,
    max_iter: int = 100,
) -> float:
    """Unguarded observed-Hessian Newton (no -Fisher guard, no line search).

    This is Layer D stripped of ``fit_ability``'s guard machinery. On the
    display-rounded battery it overshoots the interior optimum and diverges to the
    theta-bound region, exposing the E -> D full-precision requirement.
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


# --- end-to-end acceptance oracle --------------------------------------------

def test_end_to_end_equals_oracle():
    cfg = resolve_config(None)
    result = run_pipeline(_oracle_inputs(), cfg, SeededRNG(0))

    assert isinstance(result, PipelineResult)

    # Layer B: verifiable outcome graded from the five weighted sub-checks.
    assert result.outcome is not None
    assert result.outcome.outcome == ORACLE_O1

    # Layer E: counterfactual normalized lift + measurement SD (full precision).
    assert result.lift.L == ORACLE_L1
    assert result.lift.s == ORACLE_S1

    # Layer D: MAP ability with Fisher-information SE (current prepended to history).
    assert approx(result.ability.theta_hat, ORACLE_THETA)
    assert approx(result.ability.se, ORACLE_SE)
    assert result.ability.n_items == 5
    assert result.ability.converged
    assert result.ability.next_item_id == "rate_limiter_trap"

    # Layer G: calibrated prediction with an asymmetric EIV interval inside (0, 1).
    assert approx(result.prediction.lin, ORACLE_LIN)
    assert approx(result.prediction.y_hat, ORACLE_YHAT)
    assert approx(result.prediction.y_lower, ORACLE_LOWER)
    assert approx(result.prediction.y_upper, ORACLE_UPPER)
    assert 0.0 < result.prediction.y_lower < result.prediction.y_hat < result.prediction.y_upper < 1.0


class _ExplodingRunner:
    """A runner that raises if invoked, proving the grader was skipped."""

    def run(self, check: SubCheck, replay: int, rng: object) -> object:  # noqa: ARG002
        raise AssertionError("grader must not run when outcome_override is set")


def test_outcome_override_skips_grader():
    cfg = resolve_config(None)
    # No checks; an exploding runner would raise if the grader were invoked.
    inputs = _oracle_inputs(checks=[], outcome_override=ORACLE_O1)
    result = run_pipeline(inputs, cfg, SeededRNG(0), runner=_ExplodingRunner())

    # The grader is bypassed entirely: no OutcomeGrade is produced.
    assert result.outcome is None

    # Downstream layers still run on the injected outcome and hit the oracle.
    assert result.lift.L == ORACLE_L1
    assert result.lift.s == ORACLE_S1
    assert approx(result.ability.theta_hat, ORACLE_THETA)
    assert approx(result.prediction.y_hat, ORACLE_YHAT)

    # The override path matches the graded path byte-for-byte downstream.
    graded = run_pipeline(_oracle_inputs(), cfg, SeededRNG(0))
    assert result.lift.to_json() == graded.lift.to_json()
    assert result.ability.to_json() == graded.ability.to_json()
    assert result.prediction.to_json() == graded.prediction.to_json()


def test_full_precision():
    """Rounding the current item's L/s shifts theta by > 1 (E -> D invariant).

    The pipeline carries Layer-E's ``L``/``s`` into Layer D unrounded and its
    guarded solver lands on the oracle. Feeding the display-rounded current
    ``L``/``s`` into the *unguarded* Newton (Layer D without its guard) diverges
    to the theta-bound region: the corrupted basin is numpy-build dependent, so we
    assert a > 1 threshold, not a pinned value.
    """
    cfg = resolve_config(None)
    result = run_pipeline(_oracle_inputs(), cfg, SeededRNG(0))

    # Full precision throughout: the pipeline never rounds its internal L/s.
    assert approx(result.ability.theta_hat, ORACLE_THETA)
    assert round(result.lift.L, 4) != result.lift.L
    assert result.lift.s != round(result.lift.s, 4)

    # Battery the pipeline assembled, but with the current L/s display-rounded.
    rounded_current = ItemObservation(
        L=round(result.lift.L, 4),
        a=1.8,
        b=0.80,
        s=round(result.lift.s, 4),
        item_id="current",
    )
    rounded_battery = [rounded_current, *_oracle_history()]
    theta_naive = _naive_newton(rounded_battery, cfg)
    assert abs(theta_naive - 0.8758) > 1.0
