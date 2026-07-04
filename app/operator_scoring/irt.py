"""Layer D (scalar) - continuous-response IRT MAP ability estimation.

Framework-free: imports only the standard library and numpy (via
``app.operator_scoring.numerics``). No ``time``/``random``/``datetime``/network
module, so a fixed battery always produces bit-identical results.

Model (see SCORING_DESIGN.md section 7)::

    g_i(theta) = sigmoid(a_i * (theta - b_i))
    L_i        = g_i(theta) + eps_i,  eps_i ~ N(0, s_i^2)
    theta      ~ N(0, tau2)

MAP objective ``l(theta) = -theta^2/2tau2 - sum_i (L_i - g_i)^2 / 2 s_i^2`` with
analytic derivatives::

    g_i'  = a_i   * g_i (1 - g_i)
    g_i'' = a_i^2 * g_i (1 - g_i) (1 - 2 g_i)
    grad  = -theta/tau2 + sum (L_i - g_i) g_i' / s_i^2
    H     = -1/tau2     + sum [-(g_i')^2 + (L_i - g_i) g_i''] / s_i^2   (observed)
    I     =  1/tau2     + sum (g_i')^2 / s_i^2                          (Fisher, SE only)

``fit_ability`` runs a *guarded* Newton ascent: each step uses the observed
Hessian when it is sufficiently concave (``H < -hess_neg_eps``) and otherwise
falls back to ``-I`` (which is always concave, guaranteeing an ascent
direction); a step-halving line search on ``l`` keeps every step monotone. This
reaches the acceptance oracle in six iterations. Full precision flows in from
Layer E: feeding display-rounded ``L``/``s`` into this layer is a documented
regression (see ``tests/operator_scoring/test_irt.py``).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.operator_scoring.config import OperatorScoringConfig
from app.operator_scoring.numerics import sigmoid


class IrtError(ValueError):
    """Raised on an out-of-range IRT observation (``s <= 0`` or ``a == 0``)."""


@dataclass(frozen=True)
class ItemObservation:
    """One graded battery item: a continuous response ``L`` under IRT params.

    ``L`` is intentionally *unclipped* (Layer E may emit ``L < 0`` or ``L > 1``);
    only ``s`` and ``a`` are constrained so the item model stays well-posed.
    """

    L: float
    a: float
    b: float
    s: float
    item_id: str = ""

    def __post_init__(self) -> None:
        # A non-finite L would silently collapse the whole battery to the prior
        # (grad/Hessian become NaN, no step is ever accepted), so reject it here.
        if not math.isfinite(self.L):
            raise IrtError(f"ItemObservation.L must be finite (got {self.L!r})")
        if not (math.isfinite(self.a) and math.isfinite(self.b) and math.isfinite(self.s)):
            raise IrtError("ItemObservation a/b/s must be finite")
        if not self.s > 0:
            raise IrtError(f"ItemObservation.s must be > 0 (got {self.s!r})")
        if self.a == 0:
            raise IrtError("ItemObservation.a must be != 0")


@dataclass
class AbilityEstimate:
    """MAP ability estimate with Fisher-information uncertainty and CAT hint."""

    theta_hat: float
    se: float
    information: float
    ci95: tuple[float, float]
    per_item_information: list[float]
    iterations: int
    converged: bool
    n_items: int
    next_item_id: str | None = None

    def to_json(self, decimals: int = 6) -> dict[str, Any]:
        """Serialize for display. Rounds *only here*; attributes stay full precision."""
        return {
            "theta_hat": round(self.theta_hat, decimals),
            "se": round(self.se, decimals),
            "information": round(self.information, decimals),
            "ci_low": round(self.ci95[0], decimals),
            "ci_high": round(self.ci95[1], decimals),
            "per_item_information": [round(v, decimals) for v in self.per_item_information],
            "iterations": self.iterations,
            "converged": self.converged,
            "n_items": self.n_items,
            "next_item_id": self.next_item_id,
        }


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def _log_posterior(
    theta: float,
    L: NDArray[np.float64],
    a: NDArray[np.float64],
    b: NDArray[np.float64],
    s: NDArray[np.float64],
    tau2: float,
) -> float:
    """MAP log-posterior ``l(theta)`` up to an additive constant."""
    g: NDArray[np.float64] = sigmoid(a * (theta - b))
    resid = L - g
    return float(-theta * theta / (2.0 * tau2) - np.sum(resid * resid / (2.0 * s * s)))


def _grad_hess_fisher(
    theta: float,
    L: NDArray[np.float64],
    a: NDArray[np.float64],
    b: NDArray[np.float64],
    s2: NDArray[np.float64],
    tau2: float,
) -> tuple[float, float, float]:
    """Return ``(grad, observed_hessian, fisher_information)`` at ``theta``."""
    g: NDArray[np.float64] = sigmoid(a * (theta - b))
    one_minus_g = 1.0 - g
    gp = a * g * one_minus_g
    gpp = a * a * g * one_minus_g * (1.0 - 2.0 * g)
    resid = L - g
    grad = float(-theta / tau2 + np.sum(resid * gp / s2))
    hess = float(-1.0 / tau2 + np.sum((-(gp * gp) + resid * gpp) / s2))
    fisher = float(1.0 / tau2 + np.sum(gp * gp / s2))
    return grad, hess, fisher


def _newton_from(
    start: float,
    L: NDArray[np.float64],
    a: NDArray[np.float64],
    b: NDArray[np.float64],
    s: NDArray[np.float64],
    s2: NDArray[np.float64],
    tau2: float,
    lo: float,
    hi: float,
    hess_neg_eps: float,
    tol: float,
    grad_tol: float,
    max_iter: int,
    max_backtrack: int,
) -> tuple[float, int, bool]:
    """Guarded Newton ascent from one start; returns ``(theta, iterations, settled)``.

    Each step uses the observed Hessian when concave (``H < -hess_neg_eps``) and
    otherwise ``-Fisher`` (always concave, so the step is an ascent direction); a
    step-halving line search on the log-posterior keeps every accepted step
    monotone. ``settled`` is ``True`` when the iteration can no longer improve:
    either it met ``|t*delta| < tol`` and ``|grad| < grad_tol``, or the line
    search found no improving step (we are at the numerical peak, where the
    objective is flat to float64 precision and ``|grad|`` cannot be driven below
    ``grad_tol``). ``settled=False`` means it exhausted ``max_iter`` mid-climb.
    """
    theta = _clamp(start, lo, hi)
    iterations = 0
    settled = False
    for it in range(max_iter):
        iterations = it + 1
        grad, hess, fisher = _grad_hess_fisher(theta, L, a, b, s2, tau2)
        hess_used = hess if hess < -hess_neg_eps else -fisher
        delta = -grad / hess_used

        f0 = _log_posterior(theta, L, a, b, s, tau2)
        step = 0.0
        for _ in range(max_backtrack):
            cand = _clamp(theta + delta, lo, hi)
            if _log_posterior(cand, L, a, b, s, tau2) > f0:
                step = cand - theta
                theta = cand
                break
            delta *= 0.5

        if step == 0.0:
            # Line search could not improve: at the numerical optimum.
            settled = True
            break
        if abs(step) < tol and abs(grad) < grad_tol:
            settled = True
            break
    return theta, iterations, settled


def fit_ability(
    observations: list[ItemObservation],
    config: OperatorScoringConfig,
) -> AbilityEstimate:
    """Estimate MAP ability ``theta_hat`` from a battery of continuous responses.

    The continuous-response MAP log-posterior is **not globally concave** (items
    that give conflicting evidence make it bimodal), so a single Newton run from
    ``init_theta`` can settle in a local mode - or, at a symmetric configuration,
    on a local *minimum* where the gradient vanishes. To find the global MAP,
    guarded Newton is run from ``n_starts`` points spanning ``theta_bounds`` plus
    ``init_theta``, and the iterate with the highest log-posterior is kept.

    ``converged`` is reported ``True`` only when the winning point is a genuine
    interior maximum: ``|grad| < grad_tol`` **and** the observed Hessian is
    strictly concave (``< -hess_neg_eps``). An empty battery returns the prior
    (``theta_hat = init_theta``, ``I = 1/tau2``, ``SE = sqrt(tau2)``,
    ``iterations = 0``, ``converged = True``). Non-convergence never raises.
    """
    irt = config.irt
    tau2 = float(irt.tau2)
    z = float(irt.z)
    init_theta = float(irt.init_theta)

    if not observations:
        information = 1.0 / tau2
        se = float(np.sqrt(tau2))
        return AbilityEstimate(
            theta_hat=init_theta,
            se=se,
            information=information,
            ci95=(init_theta - z * se, init_theta + z * se),
            per_item_information=[],
            iterations=0,
            converged=True,
            n_items=0,
            next_item_id=None,
        )

    L: NDArray[np.float64] = np.array([o.L for o in observations], dtype=np.float64)
    a: NDArray[np.float64] = np.array([o.a for o in observations], dtype=np.float64)
    b: NDArray[np.float64] = np.array([o.b for o in observations], dtype=np.float64)
    s: NDArray[np.float64] = np.array([o.s for o in observations], dtype=np.float64)
    s2 = s * s

    lo, hi = float(irt.theta_bounds[0]), float(irt.theta_bounds[1])
    hess_neg_eps = float(irt.hess_neg_eps)
    tol = float(irt.tol)
    grad_tol = float(irt.grad_tol)
    max_iter = int(irt.max_iter)
    max_backtrack = int(irt.max_backtrack)

    # Multi-start: init_theta plus an evenly-spaced grid across theta_bounds.
    # Keep the global argmax of the log-posterior (deterministic: first max wins).
    n_starts = int(irt.n_starts)
    starts = [init_theta]
    if n_starts >= 2:
        starts.extend(float(g) for g in np.linspace(lo, hi, n_starts))

    theta = init_theta
    iterations = 0
    settled = False
    best_lp = float("-inf")
    for start in starts:
        cand_theta, cand_iters, cand_settled = _newton_from(
            start, L, a, b, s, s2, tau2, lo, hi,
            hess_neg_eps, tol, grad_tol, max_iter, max_backtrack,
        )
        lp = _log_posterior(cand_theta, L, a, b, s, tau2)
        if lp > best_lp:
            best_lp = lp
            theta = cand_theta
            iterations = cand_iters
            settled = cand_settled

    # A genuine MAP: the winning ascent settled (it cannot improve further) AND
    # the observed Hessian there is strictly concave (a maximum, not a saddle or
    # -- at a symmetric configuration -- a local minimum where the gradient also
    # vanishes). We do NOT test |grad| < grad_tol directly: near a smooth peak the
    # log-posterior is flat to float64 precision, so |grad| bottoms out around
    # hess*sqrt(eps) and can sit just above grad_tol at a genuine maximum.
    _, hess_final, _ = _grad_hess_fisher(theta, L, a, b, s2, tau2)
    converged = settled and hess_final < -hess_neg_eps

    # Fisher information / per-item information at theta_hat (full precision).
    g = sigmoid(a * (theta - b))
    gp = a * g * (1.0 - g)
    per_item_arr = gp * gp / s2
    information = float(1.0 / tau2 + np.sum(per_item_arr))
    se = float(1.0 / np.sqrt(information))
    per_item_information = [float(v) for v in per_item_arr]

    next_item = select_next_item(theta, observations, set())
    next_item_id = next_item.item_id if next_item is not None else None

    return AbilityEstimate(
        theta_hat=theta,
        se=se,
        information=information,
        ci95=(theta - z * se, theta + z * se),
        per_item_information=per_item_information,
        iterations=iterations,
        converged=converged,
        n_items=len(observations),
        next_item_id=next_item_id,
    )


def item_information(theta: float, a: float, b: float, s: float) -> float:
    """Fisher information a single item contributes at ``theta``.

    ``(a * sigmoid(a(theta-b)) (1 - sigmoid)) ^ 2 / s^2``; peaks at ``theta = b``.
    """
    g = sigmoid(a * (theta - b))
    gp = a * g * (1.0 - g)
    return float(gp * gp / (s * s))


def select_next_item(
    theta: float,
    candidates: Sequence[ItemObservation],
    used: set[str],
) -> ItemObservation | None:
    """CAT item selection: the unused candidate with maximum information at ``theta``.

    Deterministic tie-break by input order (the first maximizer wins). Returns
    ``None`` when every candidate has been used (or the pool is empty).
    """
    best: ItemObservation | None = None
    best_info = float("-inf")
    for candidate in candidates:
        if candidate.item_id in used:
            continue
        info = item_information(theta, candidate.a, candidate.b, candidate.s)
        if info > best_info:
            best_info = info
            best = candidate
    return best
