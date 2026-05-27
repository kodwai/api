from __future__ import annotations

from app.services.scoring.models import ScoringContext, SignalResult


def trap_coverage(ctx: ScoringContext) -> SignalResult:
    if not ctx.judgment or "trap_coverage" not in ctx.judgment:
        return SignalResult(0.0, "LLM judging unavailable (no API key)", skipped=True)
    j = ctx.judgment["trap_coverage"]
    return SignalResult(round(float(j["score"]) / 10.0, 3), j.get("reason", ""), j.get("evidence", []))


def baseline_lift(ctx: ScoringContext) -> SignalResult:
    """Static baseline (v1): weight is 0 in default profiles, so this never moves the
    headline score yet. Reports the delta for the badge once challenge.ai_baseline is set."""
    baseline = ctx.challenge.get("ai_baseline")
    if baseline is None:
        return SignalResult(0.0, "no AI baseline recorded yet", skipped=True)
    return SignalResult(0.0, f"baseline={baseline} (lift computed at assembly time)")
