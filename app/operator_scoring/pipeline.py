"""Pipeline composition: wire Layers B -> E -> D -> G into one call.

:func:`run_pipeline` composes the four operator-scoring layers end to end for a
single submission:

    O   = grade_outcome(...).outcome   (Layer B; or ``outcome_override`` verbatim)
    L,s = compute_lift(O, ...)         (Layer E)
    theta_hat +/- SE = fit_ability([current, *history])   (Layer D)
    Y_hat = predict(theta_hat, SE, v, agent, calibration)  (Layer G)

The load-bearing invariant is **full precision throughout**: the Layer-E outputs
``L`` and ``s`` flow into the ``ItemObservation`` for Layer D unrounded (feeding
the display-rounded values shifts ``theta_hat`` into a wrong basin), and rounding
happens *only* inside :meth:`PipelineResult.to_json`.

Framework-free: this module imports only the standard library, numpy, and the
sibling core layers. Its sole entropy source is the injected :class:`SeededRNG`,
whose underlying generator is handed to the grader; nothing here draws directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.operator_scoring.calibration_store import CalibrationParams
from app.operator_scoring.config import OperatorScoringConfig
from app.operator_scoring.grader import (
    OutcomeGrade,
    StaticRunner,
    SubCheck,
    SubCheckRunner,
    grade_outcome,
)
from app.operator_scoring.irt import AbilityEstimate, ItemObservation, fit_ability
from app.operator_scoring.lift import BaselineStats, LiftResult, compute_lift
from app.operator_scoring.numerics import SeededRNG
from app.operator_scoring.predictive import Prediction, predict


@dataclass
class PipelineInputs:
    """Everything :func:`run_pipeline` needs for one submission.

    ``checks`` drive Layer B and are ignored when ``outcome_override`` is set (the
    live path already has a graded outcome). ``current_a``/``current_b`` are the
    IRT parameters of the item being scored; ``baseline``/``ceiling``/
    ``sigma_intrinsic`` are its Layer-E calibration. ``history`` holds the
    operator's other battery items as full-precision :class:`ItemObservation`s.
    ``v``/``agent`` are the Layer-G covariates; ``calibration`` overrides the
    config-default Layer-G weights when present.
    """

    checks: list[SubCheck]
    current_a: float
    current_b: float
    baseline: BaselineStats
    ceiling: float
    sigma_intrinsic: float
    history: list[ItemObservation] = field(default_factory=list)
    v: float = 0.0
    agent: float = 0.0
    calibration: CalibrationParams | None = None
    outcome_override: float | None = None


@dataclass
class PipelineResult:
    """The four-layer output for one submission.

    ``outcome`` is ``None`` when ``outcome_override`` bypassed the grader. Every
    field stays full precision; :meth:`to_json` is the only place rounding occurs
    (delegated to each layer's own ``to_json``).
    """

    outcome: OutcomeGrade | None
    lift: LiftResult
    ability: AbilityEstimate
    prediction: Prediction

    def to_json(self) -> dict[str, Any]:
        """Serialize the whole pipeline; rounding is display-only, per layer."""
        return {
            "outcome": self.outcome.to_json() if self.outcome is not None else None,
            "lift": self.lift.to_json(),
            "ability": self.ability.to_json(),
            "prediction": self.prediction.to_json(),
        }


def _default_calibration(config: OperatorScoringConfig) -> CalibrationParams:
    """Build the config-default Layer-G calibration record (graceful fallback).

    Mirrors :func:`fit_predictive`'s empty-dataset path: the configured default
    ``gamma``/``sigma_reg``/``calibration_method`` become an unfitted
    :class:`CalibrationParams`, so ``predict`` degrades gracefully when no learned
    calibration was supplied.
    """
    pred = config.predictive
    return CalibrationParams(
        gamma=tuple(float(g) for g in pred.gamma),
        feature_names=tuple(str(f) for f in pred.feature_names),
        method=pred.calibration_method,
        sigma_reg=float(pred.sigma_reg),
    )


def run_pipeline(
    inputs: PipelineInputs,
    config: OperatorScoringConfig,
    rng: SeededRNG,
    runner: SubCheckRunner | None = None,
) -> PipelineResult:
    """Compose Layers B -> E -> D -> G into one full-precision result.

    Layer B grades ``inputs.checks`` through ``runner`` (a :class:`StaticRunner`
    when ``runner`` is ``None``) unless ``inputs.outcome_override`` is set, in
    which case that outcome is used verbatim and the grader is skipped
    (``PipelineResult.outcome`` is then ``None``). Layer E maps the outcome to
    ``(L, s)``; the current item's ``ItemObservation`` is built from those
    **unrounded** values and prepended to ``inputs.history`` before Layer D fits
    the ability. Layer G predicts ``Y`` from ``inputs.calibration`` (or the config
    default). Rounding happens only in :meth:`PipelineResult.to_json`.
    """
    # --- Layer B: verifiable outcome (or the injected override) --------------
    if inputs.outcome_override is not None:
        grade: OutcomeGrade | None = None
        outcome = float(inputs.outcome_override)
    else:
        active_runner: SubCheckRunner = runner if runner is not None else StaticRunner()
        grade = grade_outcome(inputs.checks, active_runner, config.grader, rng.generator())
        outcome = grade.outcome

    # --- Layer E: counterfactual normalized lift (full precision) ------------
    lift = compute_lift(
        outcome,
        inputs.baseline,
        inputs.ceiling,
        inputs.sigma_intrinsic,
        config,
    )

    # --- Layer D: current item (FULL PRECISION L/s) prepended to history -----
    current = ItemObservation(
        L=lift.L,
        a=inputs.current_a,
        b=inputs.current_b,
        s=lift.s,
        item_id="current",
    )
    observations = [current, *inputs.history]
    ability = fit_ability(observations, config)

    # --- Layer G: calibrated prediction with EIV interval --------------------
    params = inputs.calibration if inputs.calibration is not None else _default_calibration(config)
    prediction = predict(ability.theta_hat, ability.se, inputs.v, inputs.agent, params, config)

    return PipelineResult(outcome=grade, lift=lift, ability=ability, prediction=prediction)
