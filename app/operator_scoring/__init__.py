"""Operator scoring core: framework-free numeric pipeline O_i -> L_i -> (theta_hat +/- SE) -> Y_hat.

This package depends only on the standard library and numpy. It exposes a clean
public facade re-exporting the key entry points and result dataclasses for each
layer, so consumers can ``from app.operator_scoring import run_pipeline`` without
reaching into submodules. Submodules remain importable directly and the package
has no import-time side effects.
"""
from __future__ import annotations

from app.operator_scoring.calibration_store import CalibrationParams
from app.operator_scoring.config import OperatorScoringConfig, resolve_config
from app.operator_scoring.grader import (
    OutcomeGrade,
    SubCheck,
    SubCheckResult,
    grade_outcome,
)
from app.operator_scoring.irt import (
    AbilityEstimate,
    ItemObservation,
    fit_ability,
)
from app.operator_scoring.irt_md import (
    AbilityEstimateMD,
    ItemObservationMD,
    fit_ability_md,
)
from app.operator_scoring.itembank import Item
from app.operator_scoring.lift import BaselineStats, LiftResult, compute_lift
from app.operator_scoring.numerics import SeededRNG
from app.operator_scoring.pipeline import (
    PipelineInputs,
    PipelineResult,
    run_pipeline,
)
from app.operator_scoring.predictive import Prediction, TrainRow, predict

__all__ = [
    # config + entropy
    "resolve_config",
    "OperatorScoringConfig",
    "SeededRNG",
    # Layer B
    "grade_outcome",
    "OutcomeGrade",
    "SubCheck",
    "SubCheckResult",
    # Layer E
    "compute_lift",
    "LiftResult",
    "BaselineStats",
    # Layer D
    "fit_ability",
    "fit_ability_md",
    "ItemObservation",
    "AbilityEstimate",
    "ItemObservationMD",
    "AbilityEstimateMD",
    # Layer G
    "predict",
    "Prediction",
    "TrainRow",
    "CalibrationParams",
    # item bank
    "Item",
    # pipeline
    "run_pipeline",
    "PipelineInputs",
    "PipelineResult",
]
