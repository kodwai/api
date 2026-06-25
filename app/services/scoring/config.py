from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field


class AxisConfig(BaseModel):
    points: float = Field(ge=0)
    signals: dict[str, float]  # signal name -> weight (>=0)


class TrapConfig(BaseModel):
    id: str
    description: str


class ScoringConfig(BaseModel):
    profile: str = "balanced"
    version: int = 1
    axes: dict[str, AxisConfig]
    traps: list[TrapConfig] = Field(default_factory=list)
    rubric: list[dict] = Field(default_factory=list)  # per-challenge anchored dimensions [{name, weight, description}]


# Default profiles. Axis points across a profile should sum to 100.
DEFAULT_PROFILES: dict[str, dict] = {
    "balanced": {
        "axes": {
            "direction": {"points": 50, "signals": {
                "spec_precision": 1.0, "verification_rigor": 1.0, "decomposition": 0.8,
                "recovery": 0.8, "intent_fidelity": 1.2, "one_shot_penalty": 1.0,
            }},
            "outcome": {"points": 35, "signals": {
                "tests": 1.5, "code_quality": 1.0, "complexity": 0.5,
            }},
            "lift": {"points": 15, "signals": {
                "trap_coverage": 1.0, "baseline_lift": 0.0,
            }},
        },
    },
    "debugging": {
        "axes": {
            "direction": {"points": 60, "signals": {
                "spec_precision": 0.6, "verification_rigor": 1.4, "decomposition": 0.6,
                "recovery": 1.4, "intent_fidelity": 1.0, "one_shot_penalty": 1.0,
            }},
            "outcome": {"points": 30, "signals": {"tests": 1.5, "code_quality": 1.0, "complexity": 0.5}},
            "lift": {"points": 10, "signals": {"trap_coverage": 1.0, "baseline_lift": 0.0}},
        },
    },
    "spec_heavy": {
        "axes": {
            "direction": {"points": 60, "signals": {
                "spec_precision": 1.5, "verification_rigor": 0.8, "decomposition": 1.0,
                "recovery": 0.6, "intent_fidelity": 1.5, "one_shot_penalty": 1.0,
            }},
            "outcome": {"points": 25, "signals": {"tests": 1.5, "code_quality": 1.0, "complexity": 0.5}},
            "lift": {"points": 15, "signals": {"trap_coverage": 1.0, "baseline_lift": 0.0}},
        },
    },
    "architecture": {
        "axes": {
            "direction": {"points": 45, "signals": {
                "spec_precision": 1.0, "verification_rigor": 0.8, "decomposition": 1.2,
                "recovery": 0.8, "intent_fidelity": 1.0, "one_shot_penalty": 1.0,
            }},
            "outcome": {"points": 40, "signals": {"tests": 1.0, "code_quality": 1.0, "complexity": 1.5}},
            "lift": {"points": 15, "signals": {"trap_coverage": 1.0, "baseline_lift": 0.0}},
        },
    },
}


# Human-readable metadata for each signal, surfaced in the pre-challenge rubric.
SIGNAL_META: dict[str, dict] = {
    "spec_precision":     {"axis": "direction", "label": "Spec Precision",     "description": "Stating clear requirements and constraints before writing code."},
    "verification_rigor": {"axis": "direction", "label": "Verification Rigor",  "description": "Checking the AI's output, catching mistakes, pushing back."},
    "decomposition":      {"axis": "direction", "label": "Decomposition",       "description": "Breaking the problem into ordered steps instead of one mega-prompt."},
    "recovery":           {"axis": "direction", "label": "Recovery",            "description": "Redirecting effectively when the AI goes down the wrong path."},
    "intent_fidelity":    {"axis": "direction", "label": "Intent Fidelity",     "description": "The final solution matches what you actually asked for."},
    "one_shot_penalty":   {"axis": "direction", "label": "Engagement",          "description": "Staying engaged and iterating, vs paste-the-spec-and-walk-away."},
    "tests":              {"axis": "outcome",   "label": "Tests",               "description": "Share of the challenge's tests your solution passes."},
    "code_quality":       {"axis": "outcome",   "label": "Code Quality",        "description": "Clean, readable code without obvious smells."},
    "complexity":         {"axis": "outcome",   "label": "Complexity",          "description": "Reasonable structure and nesting."},
    "trap_coverage":      {"axis": "lift",      "label": "Edge-Case Coverage",  "description": "Handling subtle requirements a careless one-shot would miss."},
    "baseline_lift":      {"axis": "lift",      "label": "Lift over AI",         "description": "How far you out-perform a solo AI on this challenge."},
}

AXIS_META: dict[str, dict] = {
    "direction":        {"label": "Direction",        "blurb": "How well you direct the AI — the skill we care about most."},
    "outcome":          {"label": "Outcome",          "blurb": "Quality of the final artifact."},
    "lift":             {"label": "Lift",             "blurb": "Going beyond what a solo AI would produce."},
    "challenge_rubric": {"label": "Challenge Rubric", "blurb": "Domain-specific dimensions for this challenge — what 2/5/8/10 looks like."},
}

# When a challenge carries a bespoke `rubric`, the engine assembles axes as
# Direction 45 / Challenge Rubric 45 / Lift 10 (Outcome is replaced by the
# bespoke rubric). The disclosure must mirror that layout so candidates see the
# rubric they'll actually be scored on, not the generic profile fallback.
_BESPOKE_LAYOUT_POINTS = {"direction": 45.0, "challenge_rubric": 45.0, "lift": 10.0}


def build_rubric(raw_scoring_config) -> dict:
    """Resolve a challenge's scoring_config into a display-ready rubric.

    When `scoring_config.rubric` is non-empty, the displayed axes mirror the
    engine's bespoke layout (Direction + Challenge Rubric + Lift, with the
    bespoke dimensions surfaced as the rubric axis's signals) so the candidate
    sees the actual scoring criteria, not the profile's generic outcome signals.
    """
    cfg = resolve_config(raw_scoring_config)
    has_bespoke = bool(cfg.rubric)
    axes = []
    for axis_name, axis_cfg in cfg.axes.items():
        # In bespoke mode, the outcome axis is replaced by the rubric axis below.
        if has_bespoke and axis_name == "outcome":
            continue
        meta = AXIS_META.get(axis_name, {"label": axis_name.title(), "blurb": ""})
        signals = [
            {
                "name": sig,
                "label": SIGNAL_META.get(sig, {}).get("label", sig),
                "description": SIGNAL_META.get(sig, {}).get("description", ""),
                "weight": weight,
            }
            for sig, weight in axis_cfg.signals.items()
            if weight > 0  # hide zero-weight signals (e.g. baseline_lift in v1)
        ]
        # Rescale the points so the disclosure reflects the engine's bespoke layout.
        points = _BESPOKE_LAYOUT_POINTS.get(axis_name, axis_cfg.points) if has_bespoke else axis_cfg.points
        axes.append({
            "name": axis_name, "label": meta["label"], "blurb": meta["blurb"],
            "points": points, "signals": signals,
        })

    if has_bespoke:
        meta = AXIS_META["challenge_rubric"]
        rubric_signals = []
        for dim in cfg.rubric:
            # cfg.rubric is a list[dict] with {name, weight, description}.
            name = dim["name"] if isinstance(dim, dict) else dim.name
            weight = dim["weight"] if isinstance(dim, dict) else dim.weight
            description = dim["description"] if isinstance(dim, dict) else dim.description
            rubric_signals.append({
                "name": name,
                "label": name,
                "description": description,  # already anchored at 2/5/8/10
                "weight": weight,
            })
        axes.append({
            "name": "challenge_rubric", "label": meta["label"], "blurb": meta["blurb"],
            "points": _BESPOKE_LAYOUT_POINTS["challenge_rubric"], "signals": rubric_signals,
        })

    return {"profile": cfg.profile, "axes": axes}


def resolve_config(raw: Optional[str | dict]) -> ScoringConfig:
    """Resolve a challenge's stored scoring_config into a ScoringConfig.

    Empty / missing config falls back to the `balanced` profile. A config with
    only {"profile": "<name>"} inherits that profile's axes. Explicit `axes`
    override the profile. Unknown profile names fall back to balanced.
    """
    data: dict = {}
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            data = {}
    elif isinstance(raw, dict):
        data = raw

    profile = data.get("profile", "balanced")
    base = DEFAULT_PROFILES.get(profile, DEFAULT_PROFILES["balanced"])

    merged = {
        "profile": profile if profile in DEFAULT_PROFILES else "balanced",
        "version": data.get("version", 1),
        "axes": data.get("axes", base["axes"]),
        "traps": data.get("traps", []),
        "rubric": data.get("rubric", []),
    }
    return ScoringConfig(**merged)
