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
    }
    return ScoringConfig(**merged)
