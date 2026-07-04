"""Layer B self-mutation test: the documented kill-rate gate + adversarial coverage.

A strong oracle must *kill* injected faults (a mutant's graded outcome drops
below ``kill_outcome_threshold``) and must actually *exercise* the adversarial /
security dimensions. This file pins both: a >=10-mutant, kind-spanning battery
that clears the 0.80 kill-rate gate, and the coverage gate that fails a
functional-only suite even at a 100% kill rate.
"""
from __future__ import annotations

import numpy as np

from app.operator_scoring.config import resolve_config
from app.operator_scoring.grader import (
    Mutation,
    ReferenceSolution,
    StaticRunner,
    SubCheck,
    SubCheckRunner,
    run_self_mutation_test,
)

# A reference solution whose payload maps each check name -> its passing value.
# runner_factory turns a (possibly mutated) payload into a StaticRunner.
_REFERENCE_PAYLOAD = {
    "functional_core": 1.0,
    "edge_adversarial": 1.0,
    "property_invariants": 1.0,
    "performance": 1.0,
    "security_fuzz": 1.0,
}

_FULL_SUITE = [
    SubCheck("functional_core", "functional", 0.35, 1.0),
    SubCheck("edge_adversarial", "edge_adversarial", 0.35, 1.0),
    SubCheck("property_invariants", "property_invariants", 0.15, 1.0),
    SubCheck("performance", "performance", 0.10, 1.0),
    SubCheck("security_fuzz", "security_fuzz", 0.05, 1.0),
]


def _runner_factory(sol: ReferenceSolution) -> SubCheckRunner:
    return StaticRunner(values=dict(sol.payload))


def _drop(*names: str):
    """A mutation apply() that fails the named checks (sets their value to 0)."""

    def apply(sol: ReferenceSolution) -> ReferenceSolution:
        payload = dict(sol.payload)
        for name in names:
            payload[name] = 0.0
        return ReferenceSolution(id=sol.id + "*", payload=payload)

    return apply


def _reference() -> ReferenceSolution:
    return ReferenceSolution(id="ref", payload=dict(_REFERENCE_PAYLOAD))


# >=10 mutants spanning single-check drops (each kind) and multi-check regressions.
_MUTANTS = [
    Mutation("m_func", "break functional_core", _drop("functional_core")),
    Mutation("m_edge", "break edge_adversarial", _drop("edge_adversarial")),
    Mutation("m_prop", "break property_invariants", _drop("property_invariants")),
    Mutation("m_perf", "break performance", _drop("performance")),
    Mutation("m_sec", "break security_fuzz", _drop("security_fuzz")),
    Mutation("m_func_edge", "break functional+edge", _drop("functional_core", "edge_adversarial")),
    Mutation("m_edge_sec", "break edge+security", _drop("edge_adversarial", "security_fuzz")),
    Mutation("m_prop_perf", "break property+performance", _drop("property_invariants", "performance")),
    Mutation("m_func_sec", "break functional+security", _drop("functional_core", "security_fuzz")),
    Mutation("m_all_but_func", "break everything but functional",
             _drop("edge_adversarial", "property_invariants", "performance", "security_fuzz")),
    Mutation("m_all", "break all checks",
             _drop("functional_core", "edge_adversarial", "property_invariants",
                   "performance", "security_fuzz")),
]


def test_mutation_kill_rate_gate():
    """>=10 kind-spanning mutants: every real regression is killed, gate passes."""
    cfg = resolve_config(None).grader
    report = run_self_mutation_test(
        _reference(), _FULL_SUITE, _MUTANTS, _runner_factory, cfg, np.random.default_rng(0)
    )
    assert report.total >= 10
    assert report.kill_rate == 1.0           # every mutant lowers O below 1.0
    assert report.gate_passed
    assert report.survivors == []
    assert report.reference_outcome == 1.0


def test_no_op_mutation_survives():
    """A no-op mutation leaves O == 1.0, so it is a listed survivor (weak-oracle signal)."""
    cfg = resolve_config(None).grader
    mutants = [*_MUTANTS, Mutation("m_noop", "no-op", None)]
    report = run_self_mutation_test(
        _reference(), _FULL_SUITE, mutants, _runner_factory, cfg, np.random.default_rng(0)
    )
    assert "m_noop" in report.survivors
    assert report.kill_rate == len(_MUTANTS) / (len(_MUTANTS) + 1)


def test_coverage_gate_fails_functional_only_suite():
    """A functional-only suite is NOT a strong oracle when adversarial coverage is required."""
    cfg = resolve_config(
        {"grader": {"mutation": {"required_kinds": ["edge_adversarial", "security_fuzz"]}}}
    ).grader
    func_only_suite = [SubCheck("functional_core", "functional", 1.0, 1.0)]
    func_only_mutants = [Mutation("m_func", "break functional", _drop("functional_core"))]
    report = run_self_mutation_test(
        _reference(), func_only_suite, func_only_mutants, _runner_factory, cfg, np.random.default_rng(0)
    )
    assert report.kill_rate == 1.0                              # kills its (functional) mutant
    assert set(report.missing_required_kinds) == {"edge_adversarial", "security_fuzz"}
    assert not report.gate_passed                              # ...but covers no adversarial kind


def test_coverage_gate_passes_when_kinds_covered():
    """With adversarial+security checks weighted, the covered suite passes the gate."""
    cfg = resolve_config(
        {"grader": {"mutation": {"required_kinds": ["edge_adversarial", "security_fuzz"]}}}
    ).grader
    report = run_self_mutation_test(
        _reference(), _FULL_SUITE, _MUTANTS, _runner_factory, cfg, np.random.default_rng(0)
    )
    assert report.missing_required_kinds == ()
    assert "edge_adversarial" in report.covered_kinds
    assert "security_fuzz" in report.covered_kinds
    assert report.gate_passed


def test_zero_weight_kind_does_not_count_as_covered():
    """A required kind present only at weight 0 does not satisfy the coverage gate."""
    cfg = resolve_config(
        {"grader": {"mutation": {"required_kinds": ["security_fuzz"]}}}
    ).grader
    suite = [
        SubCheck("functional_core", "functional", 1.0, 1.0),
        SubCheck("security_fuzz", "security_fuzz", 0.0, 1.0),  # present but unweighted
    ]
    mutants = [Mutation("m_func", "break functional", _drop("functional_core"))]
    report = run_self_mutation_test(
        _reference(), suite, mutants, _runner_factory, cfg, np.random.default_rng(0)
    )
    assert "security_fuzz" in report.missing_required_kinds
    assert not report.gate_passed
