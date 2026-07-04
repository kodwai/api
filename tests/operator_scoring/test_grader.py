from __future__ import annotations

import numpy as np
import pytest

from app.operator_scoring.config import GraderConfig
from app.operator_scoring.grader import (
    GraderConfigError,
    Mutation,
    MutationReport,
    OutcomeGrade,
    ReferenceSolution,
    RunOutcome,
    StaticRunner,
    SubCheck,
    grade_outcome,
    run_self_mutation_test,
)
from tests.operator_scoring.conftest import approx, make_rng

# --- oracle battery (SCORING_DESIGN sections 5 & 12) --------------------------

def _oracle_checks() -> list[SubCheck]:
    # (name, kind, weight, result); sum(weight) == 1.0 exactly.
    return [
        SubCheck("functional_core", "functional", 0.35, 1.0),
        SubCheck("edge_adversarial", "edge_adversarial", 0.35, 0.7),
        SubCheck("property_invariants", "property_invariants", 0.15, 1.0),
        SubCheck("performance", "performance", 0.10, 0.5),
        SubCheck("security_fuzz", "security_fuzz", 0.05, 1.0),
    ]


def test_oracle_O1():
    checks = _oracle_checks()
    grade = grade_outcome(checks, StaticRunner(), GraderConfig(), make_rng(), replays=1)

    # Full precision: the np.dot weighted sum reproduces O1 == 0.845 EXACTLY.
    assert grade.outcome == 0.845
    assert grade.raw_mean == 0.845
    assert grade.flakiness == 0.0
    assert grade.deterministic is True
    assert grade.replays == 1
    assert grade.weight_sum == 1.0
    assert grade.errored_checks == []
    assert grade.oracle_strong is None
    assert len(grade.checks) == 5
    # sum of weights is exactly 1.0
    assert sum(c.weight for c in grade.checks) == 1.0
    # per-check values recorded verbatim at R=1
    by_name = {c.name: c for c in grade.checks}
    assert by_name["edge_adversarial"].mean_value == 0.7
    assert all(c.stdev == 0.0 and c.flaky is False for c in grade.checks)


def test_oracle_display_rounds_to_0_845():
    grade = grade_outcome(_oracle_checks(), StaticRunner(), GraderConfig(), make_rng(), replays=1)
    js = grade.to_json()
    assert js["outcome"] == 0.845
    assert js["flakiness"] == 0.0
    assert js["deterministic"] is True
    assert js["weight_sum"] == 1.0
    assert len(js["checks"]) == 5


def test_oracle_report_sets_oracle_strong():
    report = MutationReport(
        kill_rate=0.9, killed=9, survived=1, total=10, threshold=0.8, gate_passed=True
    )
    grade = grade_outcome(
        _oracle_checks(), StaticRunner(), GraderConfig(), make_rng(),
        replays=1, oracle_report=report,
    )
    assert grade.oracle_strong is True
    assert grade.outcome == 0.845


# --- weight policy: normalize / strict ---------------------------------------

def test_weight_policy_normalize_rescales_to_sum_one():
    # Weights sum to 2.0; normalize divides by the sum. All results 1.0 -> O == 1.0.
    checks = [
        SubCheck("a", "functional", 1.0, 1.0),
        SubCheck("b", "edge_adversarial", 1.0, 1.0),
    ]
    cfg = GraderConfig(weight_policy="normalize")
    grade = grade_outcome(checks, StaticRunner(), cfg, make_rng(), replays=1)
    assert approx(grade.outcome, 1.0, 1e-12)
    assert grade.weight_sum == 2.0
    assert grade.normalized is True


def test_weight_policy_normalize_noop_when_already_unit_sum():
    grade = grade_outcome(_oracle_checks(), StaticRunner(), GraderConfig(), make_rng(), replays=1)
    # sum(w) already == 1 within tolerance, so no rescale flag is raised.
    assert grade.normalized is False


def test_weight_policy_strict_passes_on_unit_sum():
    cfg = GraderConfig(weight_policy="strict")
    grade = grade_outcome(_oracle_checks(), StaticRunner(), cfg, make_rng(), replays=1)
    assert grade.outcome == 0.845
    assert grade.normalized is False


def test_weight_policy_strict_raises_off_unit_sum():
    checks = [
        SubCheck("a", "functional", 0.6, 1.0),
        SubCheck("b", "edge_adversarial", 0.6, 1.0),
    ]
    cfg = GraderConfig(weight_policy="strict")
    with pytest.raises(GraderConfigError):
        grade_outcome(checks, StaticRunner(), cfg, make_rng(), replays=1)


# --- on_check_error: zero / skip / fail --------------------------------------

class _RaisingRunner:
    """Runner that raises for a target check name, else returns check.result."""

    def __init__(self, bad: str) -> None:
        self._bad = bad

    def run(self, check: SubCheck, replay: int, rng: np.random.Generator) -> RunOutcome:
        if check.name == self._bad:
            raise RuntimeError(f"boom in {check.name}")
        assert check.result is not None
        return RunOutcome(value=float(check.result))


def _two_checks() -> list[SubCheck]:
    return [
        SubCheck("good", "functional", 0.5, 1.0),
        SubCheck("bad", "edge_adversarial", 0.5, 1.0),
    ]


def test_on_check_error_zero_keeps_weight_scores_zero():
    cfg = GraderConfig(on_check_error="zero")
    grade = grade_outcome(_two_checks(), _RaisingRunner("bad"), cfg, make_rng(), replays=1)
    # good contributes 0.5*1.0; bad kept at weight 0.5 but c=0 -> O == 0.5.
    assert approx(grade.outcome, 0.5, 1e-12)
    assert grade.errored_checks == ["bad"]
    assert grade.weight_sum == 1.0


def test_on_check_error_skip_drops_and_renormalizes():
    cfg = GraderConfig(on_check_error="skip")
    grade = grade_outcome(_two_checks(), _RaisingRunner("bad"), cfg, make_rng(), replays=1)
    # bad dropped; good renormalized to weight 1.0 -> O == 1.0.
    assert approx(grade.outcome, 1.0, 1e-12)
    assert grade.errored_checks == ["bad"]
    assert grade.weight_sum == 0.5   # only the active check's raw weight
    assert grade.normalized is True


def test_on_check_error_fail_zeros_whole_outcome():
    cfg = GraderConfig(on_check_error="fail")
    grade = grade_outcome(_two_checks(), _RaisingRunner("bad"), cfg, make_rng(), replays=1)
    assert grade.outcome == 0.0
    assert grade.errored_checks == ["bad"]


def test_runner_ok_false_is_treated_as_error():
    class _NotOkRunner:
        def run(self, check: SubCheck, replay: int, rng: np.random.Generator) -> RunOutcome:
            if check.name == "bad":
                return RunOutcome(value=0.3, ok=False, error="soft-fail")
            assert check.result is not None
            return RunOutcome(value=float(check.result))

    cfg = GraderConfig(on_check_error="zero")
    grade = grade_outcome(_two_checks(), _NotOkRunner(), cfg, make_rng(), replays=1)
    assert grade.errored_checks == ["bad"]
    by_name = {c.name: c for c in grade.checks}
    assert by_name["bad"].errored is True
    assert by_name["bad"].error == "soft-fail"
    assert approx(grade.outcome, 0.5, 1e-12)


# --- flakiness ----------------------------------------------------------------

class _FlakyRunner:
    """Deterministic-but-flaky: alternates value by replay parity."""

    def run(self, check: SubCheck, replay: int, rng: np.random.Generator) -> RunOutcome:
        return RunOutcome(value=0.9 if replay % 2 == 0 else 0.7)


def test_flaky_runner_produces_positive_flakiness():
    checks = [SubCheck("only", "functional", 1.0, None)]
    grade = grade_outcome(checks, _FlakyRunner(), GraderConfig(), make_rng(), replays=4)
    # O_r alternates 0.9 / 0.7 -> mean 0.8, std 0.1.
    assert approx(grade.raw_mean, 0.8, 1e-12)
    assert grade.flakiness > 0.0
    assert approx(grade.flakiness, 0.1, 1e-9)
    # penalized: O = 0.8 - 1.0 * 0.1 = 0.7
    assert approx(grade.outcome, 0.7, 1e-9)
    assert grade.deterministic is False   # 0.1 > flakiness_threshold (0.05)
    assert grade.checks[0].flaky is True


def test_flakiness_penalty_weight_zero_disables_penalty():
    checks = [SubCheck("only", "functional", 1.0, None)]
    cfg = GraderConfig(flakiness_penalty_weight=0.0)
    grade = grade_outcome(checks, _FlakyRunner(), cfg, make_rng(), replays=4)
    assert approx(grade.outcome, 0.8, 1e-12)   # no penalty subtracted
    assert grade.flakiness > 0.0


# --- empty battery ------------------------------------------------------------

def test_empty_checks_yield_zero_no_zero_division():
    grade = grade_outcome([], StaticRunner(), GraderConfig(), make_rng(), replays=3)
    assert isinstance(grade, OutcomeGrade)
    assert grade.outcome == 0.0
    assert grade.weight_sum == 0.0
    assert grade.checks == []
    assert grade.deterministic is True
    js = grade.to_json()
    assert js["outcome"] == 0.0
    assert js["checks"] == []


def test_all_zero_weights_no_zero_division():
    checks = [
        SubCheck("a", "functional", 0.0, 1.0),
        SubCheck("b", "edge_adversarial", 0.0, 1.0),
    ]
    grade = grade_outcome(checks, StaticRunner(), GraderConfig(), make_rng(), replays=1)
    assert grade.outcome == 0.0
    assert grade.weight_sum == 0.0


# --- SubCheck validation ------------------------------------------------------

def test_subcheck_rejects_bad_kind_and_result():
    with pytest.raises(GraderConfigError):
        SubCheck("x", "not_a_kind", 0.5, 1.0)
    with pytest.raises(GraderConfigError):
        SubCheck("x", "functional", -0.1, 1.0)
    with pytest.raises(GraderConfigError):
        SubCheck("x", "functional", 0.5, 1.7)


# --- self-mutation test: >=3 killers + 1 no-op survivor ----------------------

def _mutation_suite() -> list[SubCheck]:
    # Binary-exact weights summing to 1.0 so the perfect reference grades to
    # exactly 1.0 under normalize (0.5 + 0.25 + 0.125 + 0.125).
    return [
        SubCheck("c_func", "functional", 0.5, None),
        SubCheck("c_edge", "edge_adversarial", 0.25, None),
        SubCheck("c_prop", "property_invariants", 0.125, None),
        SubCheck("c_perf", "performance", 0.125, None),
    ]


def _payload_runner_factory(sol: ReferenceSolution) -> StaticRunner:
    # A check returns its payload override if present, else 1.0 (the correct value).
    values = {c: float(sol.payload[c]) for c in sol.payload}
    merged = {name: values.get(name, 1.0) for name in ("c_func", "c_edge", "c_prop", "c_perf")}
    return StaticRunner(values=merged)


def _killer(mut_id: str, check_name: str) -> Mutation:
    def apply(sol: ReferenceSolution) -> ReferenceSolution:
        payload = dict(sol.payload)
        payload[check_name] = 0.0   # break exactly one check
        return ReferenceSolution(id=sol.id, payload=payload)

    return Mutation(id=mut_id, description=f"break {check_name}", apply=apply)


def test_self_mutation_kill_rate_and_gate():
    reference = ReferenceSolution(id="ref", payload={})
    suite = _mutation_suite()
    mutations = [
        _killer("m1", "c_func"),
        _killer("m2", "c_edge"),
        _killer("m3", "c_prop"),
        _killer("m4", "c_perf"),
        Mutation(id="noop", description="no-op survivor", apply=None),
    ]
    report = run_self_mutation_test(
        reference, suite, mutations, _payload_runner_factory, GraderConfig(), make_rng()
    )
    assert isinstance(report, MutationReport)
    assert report.total == 5
    assert report.killed == 4                 # 4 killers each drop O below 1.0
    assert report.survived == 1
    assert report.survivors == ["noop"]       # the no-op fault is missed
    assert approx(report.kill_rate, 0.8, 1e-12)
    assert report.gate_passed is True         # 0.8 >= kill_rate_threshold (0.80)
    assert approx(report.reference_outcome, 1.0, 1e-12)
    js = report.to_json()
    assert js["killed"] == 4
    assert js["gate_passed"] is True


def test_self_mutation_gate_fails_below_threshold():
    reference = ReferenceSolution(id="ref", payload={})
    suite = _mutation_suite()
    # 3 killers + 2 no-op survivors -> kill_rate 0.6 < 0.80 -> gate fails.
    mutations = [
        _killer("m1", "c_func"),
        _killer("m2", "c_edge"),
        _killer("m3", "c_prop"),
        Mutation(id="noop1", apply=None),
        Mutation(id="noop2", apply=None),
    ]
    report = run_self_mutation_test(
        reference, suite, mutations, _payload_runner_factory, GraderConfig(), make_rng()
    )
    assert report.killed == 3
    assert approx(report.kill_rate, 0.6, 1e-12)
    assert report.gate_passed is False
    assert sorted(report.survivors) == ["noop1", "noop2"]


def test_self_mutation_reference_failure_raises():
    # A reference whose payload breaks a check fails its own suite -> raise.
    bad_reference = ReferenceSolution(id="bad", payload={"c_func": 0.0})
    with pytest.raises(GraderConfigError):
        run_self_mutation_test(
            bad_reference, _mutation_suite(), [Mutation(id="m1", apply=None)],
            _payload_runner_factory, GraderConfig(), make_rng(),
        )
