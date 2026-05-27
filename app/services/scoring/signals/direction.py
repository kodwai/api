from __future__ import annotations

import re

from app.services.scoring.models import ScoringContext, SignalResult

# Words signalling the human caught/corrected the AI (EN + TR).
_CORRECTION = re.compile(
    r"\b(no|nope|wrong|incorrect|instead|actually|should(n't)?|don't|revert|undo|fix|"
    r"hayır|yanlış|olmamış|düzelt|geri al|değil|aslında)\b",
    re.IGNORECASE,
)


def _user_turns(ctx: ScoringContext) -> list[dict]:
    return [t for t in ctx.turns if t.get("role") == "user" and (t.get("content") or "").strip()]


def one_shot_penalty(ctx: ScoringContext) -> SignalResult:
    """1.0 = the human stayed engaged and iterated; ~0 = paste-spec-and-walk-away."""
    users = _user_turns(ctx)
    if not users:
        return SignalResult(0.0, "no human turns in trace — looks fully automated", skipped=False)
    # The first user turn is usually the spec/kickoff; count meaningful follow-ups.
    followups = [t for t in users[1:] if len(t["content"].strip()) > 20]
    value = min(1.0, len(followups) / 3.0)
    ev = [t["content"][:160] for t in followups[:2]]
    return SignalResult(round(value, 3), f"{len(followups)} meaningful follow-up prompts", ev)


def recovery(ctx: ScoringContext) -> SignalResult:
    """How well the human redirected after the AI went wrong. Neutral when nothing went wrong."""
    users = _user_turns(ctx)
    corrections = [t for t in users if _CORRECTION.search(t["content"])]
    if not corrections:
        return SignalResult(0.7, "no explicit corrections detected (neutral)")
    value = min(1.0, len(corrections) / 2.0)
    return SignalResult(round(value, 3), f"{len(corrections)} corrective steer(s)",
                        [c["content"][:160] for c in corrections[:2]])


def _from_judgment(ctx: ScoringContext, name: str) -> SignalResult:
    if not ctx.judgment or name not in ctx.judgment:
        return SignalResult(0.0, "LLM judging unavailable (no API key)", skipped=True)
    j = ctx.judgment[name]
    return SignalResult(round(float(j["score"]) / 10.0, 3), j.get("reason", ""), j.get("evidence", []))


def spec_precision(ctx: ScoringContext) -> SignalResult:
    return _from_judgment(ctx, "spec_precision")


def verification_rigor(ctx: ScoringContext) -> SignalResult:
    return _from_judgment(ctx, "verification_rigor")


def decomposition(ctx: ScoringContext) -> SignalResult:
    return _from_judgment(ctx, "decomposition")


def intent_fidelity(ctx: ScoringContext) -> SignalResult:
    return _from_judgment(ctx, "intent_fidelity")
