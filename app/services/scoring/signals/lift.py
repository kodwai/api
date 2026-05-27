from __future__ import annotations

from app.services.scoring.models import ScoringContext, SignalResult


def trap_coverage(ctx: ScoringContext) -> SignalResult:
    if not ctx.judgment or "trap_coverage" not in ctx.judgment:
        return SignalResult(0.0, "LLM judging unavailable (no API key)", skipped=True)
    j = ctx.judgment["trap_coverage"]
    return SignalResult(round(float(j["score"]) / 10.0, 3), j.get("reason", ""), j.get("evidence", []))


def baseline_lift(ctx: ScoringContext) -> SignalResult:
    """Static baseline (v1): weight is 0 in default profiles, so this never moves the
    headline score yet. The delta for the badge is computed in engine._assemble, not here.
    Always skipped so a non-zero weight can never accidentally drag the axis score down
    with a zero value before real lift computation exists.
    # TODO(KOD-78): compute real normalized lift once live baselines exist."""
    return SignalResult(0.0, "baseline lift not yet scored (see engine._assemble for badge delta)", skipped=True)
