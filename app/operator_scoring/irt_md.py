"""Layer D (multidimensional) - continuous-response IRT MAP ability over R^D.

Framework-free: imports only the standard library, numpy (via
``app.operator_scoring.numerics``) and the scalar Layer-D module
``app.operator_scoring.irt`` (for the shared :class:`IrtError`). No
``time``/``random``/``datetime``/network module, so a fixed battery always
produces bit-identical results.

Model (see SCORING_DESIGN.md section 7). Ability ``theta in R^D`` over the named
dimensions ``("dec","ver","rec","taste","eff")``; each observation carries a
discrimination *vector* ``a_vec`` and a linear-predictor intercept ``b``::

    g_i(theta) = sigmoid(a_vec_i . theta - b_i)
    L_i        = g_i(theta) + eps_i,  eps_i ~ N(0, s_i^2)
    theta      ~ N(0, tau2 * I_D)

With ``h_i = g_i (1 - g_i)`` the MAP gradient and (expected) Fisher matrix are::

    grad = -theta/tau2 + sum_i (L_i - g_i) h_i / s_i^2 * a_vec_i
    I    = (1/tau2) I_D + sum_i (h_i^2 / s_i^2) a_vec_i a_vec_i^T

``fit_ability_md`` runs a *matrix-guarded* Newton (Fisher scoring): the Fisher
matrix is symmetric positive-definite for every theta (its ``(1/tau2) I_D``
prior term alone is PD, and ``md_ridge`` is added before every inversion), so
``step = solve(I, grad)`` is always an ascent *direction*. A full unit step
along an ascent direction can still overshoot and *decrease* the objective, so
a step-halving line search on the MD log-posterior (identical in spirit to the
scalar solver's) accepts the full step only when it improves and otherwise
halves it. Per-dimension standard errors are the square roots of the diagonal
of ``I^-1``.

``dimension_observation`` is the *only* sanctioned scalar -> MD lift: it sets
``a_vec = a * e_dim`` and ``b_MD = a * b_scalar`` so that a one-dimensional MD
battery reproduces the scalar oracle (``irt.fit_ability``) exactly. Objective
process signals enter as extra one-hot per-dimension observations (e.g. a
verification-rigor signal is a one-hot observation on the ``ver`` axis).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from app.operator_scoring.config import OperatorScoringConfig
from app.operator_scoring.irt import IrtError
from app.operator_scoring.numerics import sigmoid


@dataclass(frozen=True)
class ItemObservationMD:
    """One graded battery item under the multidimensional IRT model.

    ``a_vec`` is the per-dimension discrimination vector and ``b`` is the
    *linear-predictor* intercept (already folded into ``a_vec . theta - b``, not
    ``a_vec . (theta - b)``). ``L`` is intentionally *unclipped* (Layer E may
    emit ``L < 0`` or ``L > 1``); only ``s`` and ``a_vec`` are constrained so the
    item model stays well-posed.
    """

    L: float
    a_vec: tuple[float, ...]
    b: float
    s: float
    item_id: str = ""

    def __post_init__(self) -> None:
        if not self.s > 0:
            raise IrtError(f"ItemObservationMD.s must be > 0 (got {self.s!r})")
        if len(self.a_vec) < 1:
            raise IrtError("ItemObservationMD.a_vec must have length >= 1")
        if not any(self.a_vec):
            raise IrtError("ItemObservationMD.a_vec must have a non-zero component")


@dataclass
class AbilityEstimateMD:
    """MAP ability estimate over ``R^D`` with a Fisher-information covariance."""

    theta_hat: tuple[float, ...]
    se: tuple[float, ...]
    information: list[list[float]]                 # DxD Fisher matrix
    ci95: tuple[tuple[float, float], ...]
    per_item_information: list[float]
    iterations: int
    converged: bool
    dims: tuple[str, ...]

    def to_json(self, decimals: int = 6) -> dict[str, Any]:
        """Serialize for display. Rounds *only here*; attributes stay full precision."""
        return {
            "theta_hat": [round(v, decimals) for v in self.theta_hat],
            "se": [round(v, decimals) for v in self.se],
            "information": [[round(v, decimals) for v in row] for row in self.information],
            "ci95": [[round(lo, decimals), round(hi, decimals)] for lo, hi in self.ci95],
            "per_item_information": [round(v, decimals) for v in self.per_item_information],
            "iterations": self.iterations,
            "converged": self.converged,
            "dims": list(self.dims),
        }


def _resolve_dims(
    observations: list[ItemObservationMD],
    config: OperatorScoringConfig,
    dims: int | None,
) -> tuple[int, tuple[str, ...]]:
    """Resolve the dimension count ``D`` and its names from config / observations."""
    if dims is not None:
        d = int(dims)
    elif observations:
        d = len(observations[0].a_vec)
    else:
        d = len(config.irt.dims)
    if d < 1:
        raise IrtError("fit_ability_md requires D >= 1")
    for obs in observations:
        if len(obs.a_vec) != d:
            raise IrtError(
                f"ItemObservationMD.a_vec length {len(obs.a_vec)} != D={d} "
                f"(item_id={obs.item_id!r})"
            )
    names = config.irt.dims
    if len(names) >= d:
        dim_names = tuple(names[:d])
    else:
        dim_names = tuple(names) + tuple(f"dim{i}" for i in range(len(names), d))
    return d, dim_names


def _fisher_matrix(
    A: NDArray[np.float64],
    w: NDArray[np.float64],
    tau2: float,
    d: int,
) -> NDArray[np.float64]:
    """Fisher matrix ``(1/tau2) I_D + sum_i w_i a_vec_i a_vec_i^T`` (unridged)."""
    fisher: NDArray[np.float64] = np.eye(d, dtype=np.float64) / tau2
    fisher = fisher + (A.T * w) @ A
    return fisher


def _md_log_posterior(
    theta: NDArray[np.float64],
    L: NDArray[np.float64],
    A: NDArray[np.float64],
    B: NDArray[np.float64],
    s2: NDArray[np.float64],
    tau2: float,
) -> float:
    """MD MAP log-posterior ``l(theta)`` up to an additive constant."""
    g: NDArray[np.float64] = sigmoid(A @ theta - B)
    resid = L - g
    return float(-float(theta @ theta) / (2.0 * tau2) - np.sum(resid * resid / (2.0 * s2)))


def fit_ability_md(
    observations: list[ItemObservationMD],
    config: OperatorScoringConfig,
    dims: int | None = None,
) -> AbilityEstimateMD:
    """Estimate MAP ability ``theta_hat in R^D`` from a battery of MD observations.

    Fisher-scoring Newton from ``init_theta * 1_D``: each step solves the ridged
    Fisher system ``(I + md_ridge I_D) step = grad`` (always PD -> always an
    ascent direction) and clamps to ``theta_bounds``; converges when the maximum
    absolute component of the actual move is ``< md_tol``. Per-dimension
    ``se_d = sqrt((I + md_ridge I_D)^-1_dd)``. An empty battery returns the prior
    (``theta_hat = init_theta``, ``I = (1/tau2) I_D``, ``iterations = 0``,
    ``converged = True``). Non-convergence never raises; it is reported via
    ``converged = False``.
    """
    irt = config.irt
    tau2 = float(irt.tau2)
    z = float(irt.z)
    init_theta = float(irt.init_theta)
    md_ridge = float(irt.md_ridge)
    md_tol = float(irt.md_tol)
    md_max_iter = int(irt.md_max_iter)
    lo, hi = float(irt.theta_bounds[0]), float(irt.theta_bounds[1])

    d, dim_names = _resolve_dims(observations, config, dims)
    ridge_eye: NDArray[np.float64] = md_ridge * np.eye(d, dtype=np.float64)

    if not observations:
        prior_fisher = np.eye(d, dtype=np.float64) / tau2
        prior_cov = np.linalg.inv(prior_fisher + ridge_eye)
        prior_se = np.sqrt(np.diag(prior_cov))
        prior_theta = np.full(d, init_theta, dtype=np.float64)
        return _assemble(prior_theta, prior_se, prior_fisher, [], 0, True, z, dim_names)

    L: NDArray[np.float64] = np.array([o.L for o in observations], dtype=np.float64)
    A: NDArray[np.float64] = np.array([o.a_vec for o in observations], dtype=np.float64)
    B: NDArray[np.float64] = np.array([o.b for o in observations], dtype=np.float64)
    s: NDArray[np.float64] = np.array([o.s for o in observations], dtype=np.float64)
    s2: NDArray[np.float64] = s * s

    theta: NDArray[np.float64] = np.full(d, init_theta, dtype=np.float64)
    iterations = 0
    converged = False
    max_backtrack = int(irt.max_backtrack)

    for it in range(md_max_iter):
        iterations = it + 1
        g: NDArray[np.float64] = sigmoid(A @ theta - B)
        h = g * (1.0 - g)
        resid = L - g
        grad: NDArray[np.float64] = -theta / tau2 + A.T @ (resid * h / s2)
        w = h * h / s2
        fisher = _fisher_matrix(A, w, tau2, d)
        step: NDArray[np.float64] = np.linalg.solve(fisher + ridge_eye, grad)

        # Step-halving line search: a Fisher-scoring step is an ascent direction
        # but a full unit step can overshoot, so accept it only when it improves
        # the log-posterior; otherwise halve it. When no fraction improves we are
        # at the numerical optimum (settled).
        f0 = _md_log_posterior(theta, L, A, B, s2, tau2)
        move = np.zeros(d, dtype=np.float64)
        frac = 1.0
        for _ in range(max_backtrack):
            cand = np.clip(theta + frac * step, lo, hi)
            if _md_log_posterior(cand, L, A, B, s2, tau2) > f0:
                move = cand - theta
                theta = cand
                break
            frac *= 0.5

        if float(np.max(np.abs(move))) == 0.0:
            converged = True  # line search could not improve: at the optimum
            break
        if float(np.max(np.abs(move))) < md_tol:
            converged = True
            break

    # Fisher information / per-item information at theta_hat (full precision).
    g = sigmoid(A @ theta - B)
    h = g * (1.0 - g)
    w = h * h / s2
    fisher = _fisher_matrix(A, w, tau2, d)
    cov = np.linalg.inv(fisher + ridge_eye)
    se_arr = np.sqrt(np.diag(cov))
    # Per-item scalar = trace of the item's DxD information contribution.
    per_item = [float(wi * float(np.dot(ai, ai))) for wi, ai in zip(w, A, strict=True)]

    return _assemble(theta, se_arr, fisher, per_item, iterations, converged, z, dim_names)


def _assemble(
    theta: NDArray[np.float64],
    se_arr: NDArray[np.float64],
    fisher: NDArray[np.float64],
    per_item: list[float],
    iterations: int,
    converged: bool,
    z: float,
    dim_names: tuple[str, ...],
) -> AbilityEstimateMD:
    """Package the raw arrays into a full-precision :class:`AbilityEstimateMD`."""
    theta_t = tuple(float(v) for v in theta)
    se_t = tuple(float(v) for v in se_arr)
    ci95 = tuple((t - z * se, t + z * se) for t, se in zip(theta_t, se_t, strict=True))
    information = [[float(v) for v in row] for row in fisher]
    return AbilityEstimateMD(
        theta_hat=theta_t,
        se=se_t,
        information=information,
        ci95=ci95,
        per_item_information=per_item,
        iterations=iterations,
        converged=converged,
        dims=dim_names,
    )


def dimension_observation(
    dim: int,
    L: float,
    a: float,
    b: float,
    s: float,
    D: int,
    item_id: str = "",
) -> ItemObservationMD:
    """Lift a scalar IRT observation onto axis ``dim`` of a ``D``-dimensional battery.

    The *only* sanctioned scalar -> MD lift: sets ``a_vec = a * e_dim`` and folds
    the scalar difficulty into the linear-predictor intercept ``b_MD = a * b`` so
    that ``a_vec . theta - b_MD = a (theta_dim - b)`` recovers the scalar item
    model exactly. With this lift a 1-D MD battery reproduces the scalar oracle.
    """
    if not 0 <= dim < D:
        raise IrtError(f"dimension_observation dim={dim} out of range for D={D}")
    a_vec = [0.0] * D
    a_vec[dim] = float(a)
    return ItemObservationMD(
        L=float(L),
        a_vec=tuple(a_vec),
        b=float(a) * float(b),
        s=float(s),
        item_id=item_id,
    )


def item_information_md(
    theta: NDArray[np.float64],
    a_vec: NDArray[np.float64],
    b: float,
    s: float,
) -> NDArray[np.float64]:
    """The ``DxD`` Fisher-information contribution of one item at ``theta``.

    ``(h^2 / s^2) a_vec a_vec^T`` with ``h = g (1 - g)`` and
    ``g = sigmoid(a_vec . theta - b)`` - the rank-1 outer product the item adds to
    the Fisher matrix.
    """
    lin = float(np.dot(a_vec, theta) - b)
    g = sigmoid(lin)
    h = g * (1.0 - g)
    outer: NDArray[np.float64] = np.outer(a_vec, a_vec)
    return (h * h / (s * s)) * outer


def select_next_item_md(
    theta: NDArray[np.float64],
    fisher: NDArray[np.float64],
    candidates: Sequence[ItemObservationMD],
    used: set[str],
) -> ItemObservationMD | None:
    """D-optimal CAT selection: the unused candidate maximizing ``log det(I + info)``.

    Adding the item whose rank-1 information contribution most increases the
    log-determinant of the Fisher matrix shrinks the joint confidence ellipsoid
    the fastest. Deterministic tie-break by input order (the first maximizer
    wins). Returns ``None`` when every candidate has been used (or the pool is
    empty).
    """
    best: ItemObservationMD | None = None
    best_score = float("-inf")
    for candidate in candidates:
        if candidate.item_id in used:
            continue
        info = item_information_md(
            theta, np.asarray(candidate.a_vec, dtype=np.float64), candidate.b, candidate.s
        )
        sign, logdet = np.linalg.slogdet(fisher + info)
        score = float(logdet) if sign > 0 else float("-inf")
        if score > best_score:
            best_score = score
            best = candidate
    return best
