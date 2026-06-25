from __future__ import annotations

from typing import Callable

from app.services.scoring.models import ScoringContext, SignalResult
from app.services.scoring.signals import direction, outcome, lift

SIGNALS: dict[str, Callable[[ScoringContext], SignalResult]] = {
    # direction
    "spec_precision": direction.spec_precision,
    "verification_rigor": direction.verification_rigor,
    "decomposition": direction.decomposition,
    "intent_fidelity": direction.intent_fidelity,
    "recovery": direction.recovery,
    "one_shot_penalty": direction.one_shot_penalty,
    # outcome
    "tests": outcome.tests,
    "code_quality": outcome.code_quality,
    "complexity": outcome.complexity,
    # lift
    "trap_coverage": lift.trap_coverage,
    "baseline_lift": lift.baseline_lift,
}


def get_signal(name: str) -> Callable[[ScoringContext], SignalResult] | None:
    return SIGNALS.get(name)
