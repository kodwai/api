"""Layer E: counterfactual normalized lift over a solo-AI baseline.

Given a graded outcome ``O`` (Layer B), a solo-AI baseline ``(mu0, sigma0, M)``
and an expert ceiling ``mu*``, this computes the normalized lift
``L = (O - mu0) / (mu* - mu0)`` (**unclipped** so ``L`` stays a monotone,
information-preserving covariate for Layer D) together with a per-observation
measurement SD ``s`` that Layer D consumes as ``ItemObservation.s``.

Full precision is load-bearing: ``L`` and ``s`` flow into Layer D at full
precision, and rounding happens *only* inside ``to_json``. Feeding the
display-rounded values into the IRT solver drives the ability estimate into a
wrong basin, so nothing here rounds the dataclass fields.

Framework-free: stdlib (``dataclasses``/``math``) + numpy only. The sole entropy
source is the injected ``numpy.random.Generator`` handed to
:func:`estimate_baseline`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import numpy as np

from app.operator_scoring.config import OperatorScoringConfig

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime coupling to itembank
    from app.operator_scoring.itembank import Item


class LiftConfigError(ValueError):
    """Raised on an out-of-range value in a Layer-E dataclass ``__post_init__``."""


class BaselineRunner(Protocol):
    """Callable that replays the reference solution for ``item`` under ``seed``.

    Returns the reference outcome ``O in [0, 1]`` for that seed. Threading the
    seed lets :func:`estimate_baseline` use common random numbers (CRN) so a
    later paired-variance reduction is auditable.
    """

    def __call__(self, item: Item, seed: int) -> float: ...


@dataclass(frozen=True)
class BaselineStats:
    """Solo-AI baseline distribution for one item.

    ``mu0``/``sigma0`` are the mean and (ddof=1) stdev of ``M`` reference
    replays. ``crn_seeds`` is either empty (no pairing) or the ``M`` seeds that
    produced ``raw_scores`` (pairing enabled), so Layer E can apply and stamp a
    common-random-numbers variance reduction.
    """

    mu0: float
    sigma0: float
    M: int
    crn_seeds: tuple[int, ...] = ()
    raw_scores: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.mu0 <= 1.0:
            raise LiftConfigError("BaselineStats.mu0 must be in [0, 1]")
        if self.sigma0 < 0:
            raise LiftConfigError("BaselineStats.sigma0 must be >= 0")
        if self.M < 1:
            raise LiftConfigError("BaselineStats.M must be >= 1")
        if len(self.crn_seeds) not in (0, self.M):
            raise LiftConfigError(
                "BaselineStats.crn_seeds must be empty or of length M"
            )

    def to_json(self) -> dict[str, object]:
        """JSON-ready view; rounds display values only (fields stay full precision)."""
        return {
            "mu0": round(self.mu0, 6),
            "sigma0": round(self.sigma0, 6),
            "M": self.M,
            "crn_seeds": list(self.crn_seeds),
            "raw_scores": [round(float(x), 6) for x in self.raw_scores],
        }


@dataclass(frozen=True)
class LiftResult:
    """Layer-E output: normalized lift ``L`` and its measurement SD ``s``.

    ``L`` is deliberately **unclipped** (may be < 0 or > 1) so it remains a
    monotone covariate for Layer D. ``ceiling_degenerate`` marks a self-muted
    item (baseline >= ceiling); ``crn_applied`` records whether a paired-variance
    reduction was actually used.
    """

    L: float
    s: float
    mu_star: float
    mu0: float
    ceiling_degenerate: bool = False
    crn_applied: bool = False

    def to_json(self, decimals: int = 4) -> dict[str, object]:
        """JSON-ready view; rounds display values only (fields stay full precision)."""
        return {
            "L": round(self.L, decimals),
            "s": round(self.s, decimals),
            "mu_star": round(self.mu_star, decimals),
            "mu0": round(self.mu0, decimals),
            "ceiling_degenerate": self.ceiling_degenerate,
            "crn_applied": self.crn_applied,
        }


def resolve_mu_star(
    ceiling: float, mu0: float, config: OperatorScoringConfig
) -> tuple[float, bool]:
    """Resolve the anchoring ceiling ``mu*`` and flag a degenerate gap.

    The ceiling is taken as ``mu*``; the gap ``mu* - mu0`` is degenerate (the
    item self-mutes) when it falls below ``config.lift.min_ceiling_gap`` (i.e.
    the baseline meets or exceeds the ceiling).
    """
    mu_star = float(ceiling)
    degenerate = (mu_star - mu0) < config.lift.min_ceiling_gap
    return mu_star, degenerate


def compute_lift(
    O: float,  # noqa: E741 - `O` is the graded outcome; pinned by SCORING_DESIGN + oracle
    baseline: BaselineStats,
    ceiling: float,
    sigma_intrinsic: float,
    config: OperatorScoringConfig,
) -> LiftResult:
    """Compute the normalized lift and its measurement SD from a graded outcome.

    ``L = (O - mu0) / (mu* - mu0)`` (unclipped) and
    ``s = sqrt(sigma_intrinsic^2 + ((sigma0/sqrt(M)) / (mu* - mu0))^2)``. When CRN
    pairing was threaded and enabled, ``s`` uses the paired-variance reduction
    ``sqrt(max(0, sigma_intrinsic^2 + v_base - 2*rho*sigma_intrinsic*sqrt(v_base)))``
    with ``rho = config.lift.crn_rho`` (``rho = 0`` recovers the base formula).
    A degenerate ceiling returns ``L = 0, s = max_se`` so Layer D's information
    ``(g')^2 / s^2`` collapses to ~0 instead of injecting inf/NaN.
    """
    mu0 = baseline.mu0
    # O is a graded outcome, in [0, 1] by construction (Layer B clips it). Clamp
    # defensively so a future/misbehaving caller passing an out-of-range O cannot
    # blow up L (and hence theta). L itself stays unclipped: O = 1 with a ceiling
    # below 1 still yields L > 1 (beat the ceiling), which is a real signal.
    O = min(1.0, max(0.0, float(O)))  # noqa: E741 - `O` pinned by SCORING_DESIGN + oracle
    mu_star, degenerate = resolve_mu_star(ceiling, mu0, config)
    if degenerate:
        return LiftResult(
            L=0.0,
            s=config.lift.max_se,
            mu_star=mu_star,
            mu0=mu0,
            ceiling_degenerate=True,
            crn_applied=False,
        )

    denom = mu_star - mu0
    lift = (O - mu0) / denom  # unclipped by design

    # Standard error of the baseline mean, mapped onto the L scale.
    base_se_l = (baseline.sigma0 / math.sqrt(baseline.M)) / denom
    v_base = base_se_l * base_se_l

    crn_applied = config.lift.crn_enabled and len(baseline.crn_seeds) > 0
    if crn_applied:
        rho = config.lift.crn_rho
        var_s = sigma_intrinsic * sigma_intrinsic + v_base - 2.0 * rho * sigma_intrinsic * base_se_l
        s = math.sqrt(max(0.0, var_s))
    else:
        s = math.sqrt(sigma_intrinsic * sigma_intrinsic + v_base)

    # A positive floor so a zero-variance baseline (sigma_intrinsic == 0 and
    # sigma0 == 0) never emits s == 0, which Layer D's ItemObservation rejects.
    s = max(s, config.lift.min_s)

    return LiftResult(
        L=lift,
        s=s,
        mu_star=mu_star,
        mu0=mu0,
        ceiling_degenerate=False,
        crn_applied=crn_applied,
    )


def estimate_baseline(
    runner: BaselineRunner,
    item: Item,
    M: int,
    rng: np.random.Generator,
    config: OperatorScoringConfig | None = None,
) -> BaselineStats:
    """Estimate a solo-AI baseline by replaying the reference ``M`` times.

    Draws ``M`` seeds from the injected generator, runs ``runner(item, seed)``
    per seed, and reports ``mu0 = mean`` and ``sigma0 = std(ddof=1)``. When
    fewer than two replays are available or the sample SD is exactly 0, ``sigma0``
    falls back to ``config.lift.prior_sigma0`` so downstream SEs stay well-posed.
    When CRN is enabled the drawn seeds are threaded into ``crn_seeds`` for a
    later paired-variance reduction.
    """
    cfg = config if config is not None else OperatorScoringConfig()
    m = max(1, int(M))

    raw_seeds = rng.integers(0, 2**31 - 1, size=m)
    seeds = tuple(int(x) for x in raw_seeds)
    scores = tuple(float(runner(item, seed)) for seed in seeds)

    arr = np.asarray(scores, dtype=np.float64)
    mu0 = float(np.mean(arr))
    if m < 2:
        sigma0 = float(cfg.lift.prior_sigma0)
    else:
        sigma0 = float(np.std(arr, ddof=1))
        if sigma0 == 0.0:
            sigma0 = float(cfg.lift.prior_sigma0)

    crn_seeds = seeds if cfg.lift.crn_enabled else ()
    return BaselineStats(
        mu0=mu0,
        sigma0=sigma0,
        M=m,
        crn_seeds=crn_seeds,
        raw_scores=scores,
    )
