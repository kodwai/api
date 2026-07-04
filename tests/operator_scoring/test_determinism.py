"""Determinism harness for the operator scoring core (SCORING_DESIGN.md section 14).

Two guarantees:

* :func:`test_no_banned_imports` AST-scans every ``app/operator_scoring/*.py`` and
  asserts its imported top-level roots never intersect the banned set (no
  ``time``/``random``/``secrets``/``datetime``/network or framework module), so the
  only entropy source is the injected ``SeededRNG``.
* :func:`test_double_run_identical` runs the full pipeline twice under a fixed
  ``SeededRNG(seed)`` and asserts byte-identical ``PipelineResult.to_json()``.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import app.operator_scoring as _core_pkg
from app.operator_scoring.calibration_store import CalibrationParams
from app.operator_scoring.config import resolve_config
from app.operator_scoring.grader import SubCheck
from app.operator_scoring.irt import ItemObservation
from app.operator_scoring.lift import BaselineStats
from app.operator_scoring.numerics import SeededRNG
from app.operator_scoring.pipeline import PipelineInputs, run_pipeline

BANNED_ROOTS = frozenset(
    {
        "time",
        "random",
        "secrets",
        "datetime",
        "socket",
        "asyncio",
        "requests",
        "urllib",
        "http",
        "fastapi",
        "pydantic",
        "pydantic_settings",
        "libsql",
        "libsql_experimental",
    }
)

_CORE_DIR = Path(_core_pkg.__file__).resolve().parent


def _imported_roots(source: str) -> set[str]:
    """Return the set of top-level module roots imported anywhere in ``source``."""
    roots: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        # Skip relative imports (``from . import x``) which have no module root.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_no_banned_imports():
    core_files = sorted(_CORE_DIR.glob("*.py"))
    assert core_files, f"no core modules found under {_CORE_DIR}"
    for path in core_files:
        roots = _imported_roots(path.read_text(encoding="utf-8"))
        offending = roots & BANNED_ROOTS
        assert not offending, f"{path.name} imports banned modules: {sorted(offending)}"


# --- deterministic double-run of the full B -> E -> D -> G pipeline ----------

_B_CHECKS: list[SubCheck] = [
    SubCheck(name="functional_core", kind="functional", weight=0.35, result=1.0),
    SubCheck(name="edge_adversarial", kind="edge_adversarial", weight=0.35, result=0.7),
    SubCheck(name="property_invariants", kind="property_invariants", weight=0.15, result=1.0),
    SubCheck(name="performance", kind="performance", weight=0.10, result=0.5),
    SubCheck(name="security_fuzz", kind="security_fuzz", weight=0.05, result=1.0),
]


def _oracle_params() -> CalibrationParams:
    return CalibrationParams(
        gamma=(-0.80, 1.10, 0.60, -0.15),
        feature_names=("theta", "v", "agent"),
        sigma_reg=0.05,
        method="none",
    )


def _pipeline_inputs() -> PipelineInputs:
    """Oracle pipeline inputs: the ledger is the current item; the rest is history."""
    return PipelineInputs(
        checks=list(_B_CHECKS),
        current_a=1.8,
        current_b=0.80,
        baseline=BaselineStats(mu0=0.55, sigma0=0.08, M=20),
        ceiling=0.97,
        sigma_intrinsic=0.10,
        history=[
            ItemObservation(L=0.92, a=0.9, b=-0.50, s=0.12, item_id="rest_crud_easy"),
            ItemObservation(L=0.45, a=2.0, b=0.50, s=0.10, item_id="rate_limiter_trap"),
            ItemObservation(L=0.68, a=1.5, b=0.60, s=0.11, item_id="search_index"),
            ItemObservation(L=0.40, a=1.6, b=1.20, s=0.13, item_id="dist_log_hard"),
        ],
        v=0.70,
        agent=1.0,
        calibration=_oracle_params(),
    )


def test_double_run_identical():
    seed = 20260704
    cfg = resolve_config(None)

    result1 = run_pipeline(_pipeline_inputs(), cfg, SeededRNG(seed))
    result2 = run_pipeline(_pipeline_inputs(), cfg, SeededRNG(seed))

    json1 = json.dumps(result1.to_json(), sort_keys=True)
    json2 = json.dumps(result2.to_json(), sort_keys=True)
    assert json1 == json2
