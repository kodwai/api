from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SignalResult:
    """One signal's verdict. value is always 0..1, higher = better."""
    value: float
    reason: str = ""
    evidence: list[str] = field(default_factory=list)
    skipped: bool = False  # True when the signal could not run (e.g. no LLM key)


@dataclass
class AxisResult:
    name: str
    points: float          # max points this axis can contribute
    score: float           # actual points earned (0..points)
    signals: list[dict]    # serialized per-signal detail for score_breakdown


@dataclass
class ScoreBreakdown:
    scoring_version: int
    overall: float
    axes: list[AxisResult]
    late_penalty: float = 0.0
    leaderboard_eligible: bool = False
    baseline_lift: Optional[dict] = None
    trace_quality: Optional[str] = None   # raw trace_quality string from agent_trace
    confidence: str = "high"              # "high"/"medium"/"low"/"none" — transparency only, does not affect score
    # Why the submission is not leaderboard-eligible, when applicable:
    # None (eligible), "no_api_key" (user has no Anthropic key), or
    # "scoring_error" (key present but the AI judge call/parse failed).
    ineligible_reason: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "scoring_version": self.scoring_version,
            "overall": self.overall,
            "late_penalty": self.late_penalty,
            "leaderboard_eligible": self.leaderboard_eligible,
            "ineligible_reason": self.ineligible_reason,
            "baseline_lift": self.baseline_lift,
            "trace_quality": self.trace_quality,
            "confidence": self.confidence,
            "axes": [
                {"name": a.name, "points": a.points, "score": a.score, "signals": a.signals}
                for a in self.axes
            ],
        }


@dataclass
class ScoringContext:
    submission: dict
    challenge: dict
    config: Any                       # ScoringConfig (avoid import cycle)
    test_results: Optional[dict]
    code_snapshot: list[dict]
    git_log: list[dict]
    agent_trace: Optional[dict]
    llm: Optional[Any] = None          # LLMJudge instance, or None when no API key
    judgment: Optional[dict] = None    # cached result of llm.judge(self)
    rubric_judgment: Optional[dict] = None  # cached result of llm.judge_rubric(self, rubric)
    has_api_key: bool = False          # whether an Anthropic key was available for judging

    @property
    def turns(self) -> list[dict]:
        if self.agent_trace and isinstance(self.agent_trace.get("turns"), list):
            return self.agent_trace["turns"]
        return []
