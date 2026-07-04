"""Layer B — verifiable outcome grader (``grade_outcome``) + self-mutation test.

The grader turns a battery of weighted, replayed hidden sub-checks into a single
verifiable outcome ``O = sum_k w_k * c_k`` with ``sum_k w_k = 1`` and
``c_k in [0, 1]``. Each check is replayed ``R`` times through an injected
:class:`SubCheckRunner`; the per-replay outcomes give a mean and a *flakiness*
``phi = std_r(O_r)`` which penalizes the score::

    O = clip(mean_r(O_r) - flakiness_penalty_weight * phi, 0, 1)

At ``R = 1`` the flakiness is ``0`` and ``O = mean`` — the acceptance-oracle
path (``O1 = 0.845``). :func:`run_self_mutation_test` proves a high ``O`` reflects
a *strong* oracle: it injects faults into a reference solution, re-grades, and
gates on the fraction of faults *killed* (``O_mut < kill_outcome_threshold``).

Framework-free: this module imports only the standard library and numpy. Its only
entropy source is the injected ``numpy.random.Generator`` handed to each runner;
the grader itself draws nothing. Full precision flows out of ``O`` into Layer E;
rounding happens only inside ``to_json()``.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from app.operator_scoring.config import GraderConfig

# Mirrors ``GraderConfig.allowed_kinds`` default; :class:`SubCheck` validates its
# ``kind`` against this at construction. ``grade_outcome`` additionally enforces
# the (possibly narrowed) ``config.allowed_kinds`` at grade time.
DEFAULT_ALLOWED_KINDS: tuple[str, ...] = (
    "functional",
    "edge_adversarial",
    "property_invariants",
    "performance",
    "security_fuzz",
)

# Float slack when checking the unmutated reference against its pass threshold:
# a normalized weighted sum of perfect checks can land at 1 - 1e-16 rather than
# exactly 1.0, and that must not be read as a reference failure.
_REF_EPS: float = 1e-9


class GraderConfigError(ValueError):
    """Raised on an ill-posed grading request (bad kind / weight policy / config)."""


def _clip01(x: float) -> float:
    """Clamp a scalar into the closed unit interval ``[0, 1]``."""
    return min(1.0, max(0.0, float(x)))


@dataclass
class SubCheck:
    """One weighted hidden sub-check.

    ``result`` is the deterministic outcome used by :class:`StaticRunner`; a live
    runner ignores it and computes its own value. ``kind`` must be one of
    :data:`DEFAULT_ALLOWED_KINDS`.
    """

    name: str
    kind: str
    weight: float
    result: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in DEFAULT_ALLOWED_KINDS:
            raise GraderConfigError(
                f"SubCheck.kind must be one of {DEFAULT_ALLOWED_KINDS}, got {self.kind!r}"
            )
        if self.weight < 0:
            raise GraderConfigError("SubCheck.weight must be >= 0")
        if self.result is not None and not (0.0 <= self.result <= 1.0):
            raise GraderConfigError("SubCheck.result must be in [0, 1] or None")


@dataclass
class RunOutcome:
    """One ``(check, replay)`` runner result. ``ok=False`` marks a caught error."""

    value: float
    ok: bool = True
    error: str = ""
    detail: str = ""


class SubCheckRunner(Protocol):
    """Injected process execution: run one check on one replay and return a value."""

    def run(self, check: SubCheck, replay: int, rng: np.random.Generator) -> RunOutcome:
        ...


@dataclass
class StaticRunner:
    """Deterministic runner: returns ``values[name]`` if present, else ``check.result``.

    Used by the acceptance oracle and by the mutation harness where the payload of
    a (possibly mutated) reference solution decides each check's value.
    """

    values: dict[str, float] | None = None

    def run(self, check: SubCheck, replay: int, rng: np.random.Generator) -> RunOutcome:
        if self.values is not None and check.name in self.values:
            return RunOutcome(value=float(self.values[check.name]))
        if check.result is not None:
            return RunOutcome(value=float(check.result))
        return RunOutcome(value=0.0)


@dataclass
class SubCheckResult:
    """Per-check aggregate across replays. ``values`` holds the raw per-replay draws."""

    name: str
    kind: str
    weight: float
    mean_value: float
    stdev: float
    values: list[float]
    flaky: bool
    errored: bool
    error: str = ""

    def to_json(self) -> dict[str, Any]:
        dp = 4
        return {
            "name": self.name,
            "kind": self.kind,
            "weight": round(self.weight, dp),
            "mean_value": round(self.mean_value, dp),
            "stdev": round(self.stdev, dp),
            "values": [round(float(v), dp) for v in self.values],
            "flaky": self.flaky,
            "errored": self.errored,
            "error": self.error,
        }


@dataclass
class OutcomeGrade:
    """Graded outcome ``O`` with flakiness, per-check detail, and provenance.

    ``outcome`` and the other numeric fields are FULL PRECISION; only
    :meth:`to_json` rounds (to ``display_dp``). ``oracle_strong`` is ``None`` when
    no mutation report was supplied, else the report's ``gate_passed``.
    """

    outcome: float
    raw_mean: float
    flakiness: float
    deterministic: bool
    replays: int
    checks: list[SubCheckResult]
    weight_sum: float
    normalized: bool
    errored_checks: list[str] = field(default_factory=list)
    oracle_strong: bool | None = None
    display_dp: int = 4

    def to_json(self) -> dict[str, Any]:
        dp = self.display_dp
        return {
            "outcome": round(self.outcome, dp),
            "raw_mean": round(self.raw_mean, dp),
            "flakiness": round(self.flakiness, dp),
            "deterministic": self.deterministic,
            "replays": self.replays,
            "weight_sum": round(self.weight_sum, dp),
            "normalized": self.normalized,
            "errored_checks": list(self.errored_checks),
            "oracle_strong": self.oracle_strong,
            "checks": [c.to_json() for c in self.checks],
        }


@dataclass
class ReferenceSolution:
    """A reference (correct) solution the mutation harness perturbs. Opaque payload."""

    id: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Mutation:
    """One injected fault. ``apply`` returns a perturbed copy; ``None`` is a no-op."""

    id: str
    description: str = ""
    apply: Callable[[ReferenceSolution], ReferenceSolution] | None = None


@dataclass
class MutationReport:
    """Result of the self-mutation test: kill rate + gate + list of survivors.

    ``covered_kinds`` are the sub-check kinds the suite carries non-zero weight on;
    ``missing_required_kinds`` are the ``config.mutation.required_kinds`` it does
    NOT cover. When any required kind is missing, ``gate_passed`` is ``False`` even
    at a 100% kill rate -- this is what stops a functional-only suite (with
    functional-only mutations) from being certified a "strong" oracle while
    testing nothing adversarial/security.
    """

    kill_rate: float
    killed: int
    survived: int
    total: int
    threshold: float
    gate_passed: bool
    survivors: list[str] = field(default_factory=list)
    reference_outcome: float = 1.0
    covered_kinds: tuple[str, ...] = ()
    missing_required_kinds: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        dp = 4
        return {
            "kill_rate": round(self.kill_rate, dp),
            "killed": self.killed,
            "survived": self.survived,
            "total": self.total,
            "threshold": round(self.threshold, dp),
            "gate_passed": self.gate_passed,
            "survivors": list(self.survivors),
            "reference_outcome": round(self.reference_outcome, dp),
            "covered_kinds": list(self.covered_kinds),
            "missing_required_kinds": list(self.missing_required_kinds),
        }


def grade_outcome(
    checks: Sequence[SubCheck],
    runner: SubCheckRunner,
    config: GraderConfig,
    rng: np.random.Generator,
    *,
    replays: int | None = None,
    oracle_report: MutationReport | None = None,
) -> OutcomeGrade:
    """Grade ``O = sum_k w_k * c_k`` over ``R`` replays with flakiness + penalty.

    ``replays`` overrides ``config.replays`` when given (the oracle passes ``1``).
    Runner exceptions are caught into ``RunOutcome(ok=False)`` and reconciled per
    ``config.on_check_error`` (``zero`` keeps the weight with ``c=0``; ``skip``
    drops the check and renormalizes; ``fail`` forces ``O=0``). ``weight_policy``
    is ``normalize`` (rescale to ``sum=1``) or ``strict`` (require ``sum==1`` to
    ``weight_sum_tolerance`` else raise). Empty / all-skipped batteries yield
    ``outcome=0.0`` with no division by zero.
    """
    strong = oracle_report.gate_passed if oracle_report is not None else None
    r_count = config.replays if replays is None else replays
    if r_count < 1:
        raise GraderConfigError("grade_outcome requires replays >= 1")

    if not checks:
        return OutcomeGrade(
            outcome=0.0,
            raw_mean=0.0,
            flakiness=0.0,
            deterministic=True,
            replays=r_count,
            checks=[],
            weight_sum=0.0,
            normalized=False,
            errored_checks=[],
            oracle_strong=strong,
            display_dp=config.display_dp,
        )

    for check in checks:
        if check.kind not in config.allowed_kinds:
            raise GraderConfigError(f"check kind not allowed by config: {check.kind!r}")

    n = len(checks)

    # --- replay each check, catching runner exceptions -----------------------
    per_values: list[list[float]] = []
    errored_flags: list[bool] = []
    error_msgs: list[str] = []
    for check in checks:
        vals: list[float] = []
        errored = False
        emsg = ""
        for replay in range(r_count):
            try:
                out = runner.run(check, replay, rng)
            except Exception as exc:  # runner failure -> a caught, errored replay
                out = RunOutcome(value=0.0, ok=False, error=repr(exc))
            if not out.ok:
                errored = True
                if not emsg:
                    emsg = out.error or "check errored"
            vals.append(_clip01(out.value))
        per_values.append(vals)
        errored_flags.append(errored)
        error_msgs.append(emsg)

    any_errored = any(errored_flags)
    fail_short = config.on_check_error == "fail" and any_errored

    # --- active mask (skip drops errored checks entirely) --------------------
    active = (
        [not e for e in errored_flags]
        if config.on_check_error == "skip"
        else [True] * n
    )

    active_weight_sum = sum(
        float(checks[k].weight) for k in range(n) if active[k]
    )

    # --- effective per-check weights + normalize/strict policy ---------------
    effective = [0.0] * n
    normalized = False
    if config.weight_policy == "strict":
        if abs(active_weight_sum - 1.0) > config.weight_sum_tolerance:
            raise GraderConfigError(
                "strict weight policy requires sum(weights) == 1 "
                f"(got {active_weight_sum!r})"
            )
        for k in range(n):
            effective[k] = float(checks[k].weight) if active[k] else 0.0
    else:  # normalize
        if active_weight_sum > 0.0:
            for k in range(n):
                effective[k] = (
                    float(checks[k].weight) / active_weight_sum if active[k] else 0.0
                )
            normalized = abs(active_weight_sum - 1.0) > config.weight_sum_tolerance
        # else all-zero effective weights -> outcome collapses to 0 (no ZeroDivision)

    eff_arr = np.asarray(effective, dtype=np.float64)

    # --- per-replay outcomes O_r (np.dot for an exact weighted sum) ----------
    o_r: list[float] = []
    for replay in range(r_count):
        vals_r = np.array(
            [
                0.0
                if (config.on_check_error == "zero" and errored_flags[k])
                else per_values[k][replay]
                for k in range(n)
            ],
            dtype=np.float64,
        )
        o_r.append(float(np.dot(eff_arr, vals_r)))

    raw_mean = float(np.mean(o_r)) if o_r else 0.0

    if config.flakiness_metric == "weighted_check_stdev":
        flakiness = 0.0
        for k in range(n):
            if active[k] and effective[k] > 0.0:
                flakiness += effective[k] * float(np.std(per_values[k]))
    else:  # aggregate_stdev
        flakiness = float(np.std(o_r)) if o_r else 0.0

    outcome = _clip01(raw_mean - config.flakiness_penalty_weight * flakiness)
    if fail_short:
        outcome = 0.0

    deterministic = flakiness <= config.flakiness_threshold

    # --- per-check aggregates ------------------------------------------------
    check_results: list[SubCheckResult] = []
    for k in range(n):
        vals = per_values[k]
        mean_v = float(np.mean(vals)) if vals else 0.0
        std_v = float(np.std(vals)) if vals else 0.0
        check_results.append(
            SubCheckResult(
                name=checks[k].name,
                kind=checks[k].kind,
                weight=float(checks[k].weight),
                mean_value=mean_v,
                stdev=std_v,
                values=list(vals),
                flaky=std_v > config.flakiness_threshold,
                errored=errored_flags[k],
                error=error_msgs[k],
            )
        )

    errored_checks = [checks[k].name for k in range(n) if errored_flags[k]]

    return OutcomeGrade(
        outcome=outcome,
        raw_mean=raw_mean,
        flakiness=flakiness,
        deterministic=deterministic,
        replays=r_count,
        checks=check_results,
        weight_sum=active_weight_sum,
        normalized=normalized,
        errored_checks=errored_checks,
        oracle_strong=strong,
        display_dp=config.display_dp,
    )


def run_self_mutation_test(
    reference_solution: ReferenceSolution,
    suite: Sequence[SubCheck],
    mutations: Sequence[Mutation],
    runner_factory: Callable[[ReferenceSolution], SubCheckRunner],
    config: GraderConfig,
    rng: np.random.Generator,
) -> MutationReport:
    """Inject each fault into ``reference_solution``, re-grade, and gate on kill rate.

    When ``config.mutation.require_reference_pass`` is set, the unmutated reference
    is graded first and must reach ``reference_pass_threshold`` (else
    :class:`GraderConfigError`) — this proves the suite passes a correct solution.
    A mutant is *killed* iff its graded ``O < kill_outcome_threshold``; survivors
    (missed faults) are listed. ``gate_passed = kill_rate >= kill_rate_threshold``
    **and** the suite covers every ``config.mutation.required_kinds`` (non-zero
    weight); a suite missing a required adversarial/security kind fails the gate
    even at a 100% kill rate. Each grade uses ``config.mutation.replays`` replays.
    """
    mc = config.mutation

    # --- adversarial-coverage gate: the suite must weight every required kind ---
    covered_kinds = tuple(
        sorted({c.kind for c in suite if c.weight > 0})
    )
    missing_required_kinds = tuple(
        k for k in mc.required_kinds if k not in covered_kinds
    )

    reference_outcome = 1.0

    if mc.require_reference_pass:
        ref_grade = grade_outcome(
            suite, runner_factory(reference_solution), config, rng, replays=mc.replays
        )
        reference_outcome = ref_grade.outcome
        if reference_outcome + _REF_EPS < mc.reference_pass_threshold:
            raise GraderConfigError(
                "reference solution failed its own suite: "
                f"O={reference_outcome!r} < {mc.reference_pass_threshold!r}"
            )

    killed = 0
    survivors: list[str] = []
    total = len(mutations)
    for mut in mutations:
        mutated = (
            mut.apply(reference_solution) if mut.apply is not None else reference_solution
        )
        grade = grade_outcome(
            suite, runner_factory(mutated), config, rng, replays=mc.replays
        )
        if grade.outcome < mc.kill_outcome_threshold:
            killed += 1
        else:
            survivors.append(mut.id)

    survived = total - killed
    kill_rate = (killed / total) if total > 0 else 0.0
    gate_passed = kill_rate >= mc.kill_rate_threshold and not missing_required_kinds

    return MutationReport(
        kill_rate=kill_rate,
        killed=killed,
        survived=survived,
        total=total,
        threshold=mc.kill_rate_threshold,
        gate_passed=gate_passed,
        survivors=survivors,
        reference_outcome=reference_outcome,
        covered_kinds=covered_kinds,
        missing_required_kinds=missing_required_kinds,
    )
