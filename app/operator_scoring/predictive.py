"""Layer G - predictive re-weighting to a real criterion Y (``predictive.py``).

Framework-free: imports only the standard library and numpy (via
``app.operator_scoring.numerics``) plus the :class:`CalibrationParams` record it
produces. No ``time``/``random``/``datetime``/network module, so a fixed dataset
always fits bit-identical weights.

Model (see SCORING_DESIGN.md section 8)::

    lin      = gamma0 + gamma1*theta + gamma2*v + gamma3*agent   (learned weights)
    Y_hat    = calib(sigmoid(lin))
    Var(lin) = gamma1^2 * SE(theta)^2 + sigma_reg^2              (errors-in-variables)
    interval = calib(sigmoid(lin +/- z*sqrt(Var(lin))))          (through the sigmoid)

``fit_predictive`` learns ``gamma`` by ridge-penalised Newton / IRLS on the
Bernoulli log-likelihood over rows ``[1, theta, v, agent]`` (ridge on the
non-intercept weights, a weight floor and a tiny Hessian jitter for
separation-robustness). The prediction interval is pushed *through* the sigmoid,
so it is bounded to ``(0, 1)`` and asymmetric. Output calibration is
config-selectable and monotone (Platt = 1-D logistic on ``lin``; Isotonic =
pure-numpy PAVA over ``(sigmoid(lin_i), y_i)``), so interval ordering is
preserved. ``calibration_method == "none"`` is the identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from app.operator_scoring.calibration_store import (
    CalibrationParams,
    IsotonicParams,
    PlattParams,
)
from app.operator_scoring.config import OperatorScoringConfig
from app.operator_scoring.numerics import sigmoid

# Numerical guards for the IRLS / Platt Newton solves.
_WEIGHT_FLOOR: float = 1e-6   # floor on the Bernoulli variance p(1-p) in the IRLS weight
_HESS_JITTER: float = 1e-10   # ridge added to the Newton Hessian diagonal for invertibility


class PredictiveError(ValueError):
    """Raised on an out-of-range predictive input (e.g. ``y`` outside ``[0, 1]``)."""


@dataclass(frozen=True)
class TrainRow:
    """One training example: operator ability ``theta``, covariates, criterion ``y``.

    ``y`` is the real criterion in ``[0, 1]`` (a hard ``{0, 1}`` label or a soft
    probability). ``agent`` is the agent-strength covariate (small by design:
    Layer E already equated agent strength).
    """

    theta: float
    v: float
    agent: float
    y: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.y <= 1.0:
            raise PredictiveError(f"TrainRow.y must be in [0, 1] (got {self.y!r})")


@dataclass(frozen=True)
class Prediction:
    """A calibrated criterion prediction with an errors-in-variables interval."""

    lin: float
    y_hat: float
    y_lower: float
    y_upper: float
    var_lin: float
    se_lin: float
    calibrated: bool = False
    calibration_method: str = "none"

    def to_json(self, decimals: int = 6) -> dict[str, Any]:
        """Serialize for display. Rounds *only here*; attributes stay full precision."""
        return {
            "lin": round(self.lin, decimals),
            "y_hat": round(self.y_hat, decimals),
            "y_lower": round(self.y_lower, decimals),
            "y_upper": round(self.y_upper, decimals),
            "var_lin": round(self.var_lin, decimals),
            "se_lin": round(self.se_lin, decimals),
            "calibrated": self.calibrated,
            "calibration_method": self.calibration_method,
        }


# --- learned weights: ridge-penalised IRLS logistic --------------------------

def fit_predictive(
    dataset: list[TrainRow],
    config: OperatorScoringConfig,
) -> CalibrationParams:
    """Fit the Layer-G weights ``gamma`` by ridge-penalised Newton / IRLS.

    Rows are ``[1, theta, v, agent]`` and the learned ``gamma = (g0, g1, g2, g3)``
    *are* the component weights. The ridge (``config.predictive.ridge_lambda``)
    penalises the non-intercept weights (also the intercept when
    ``penalize_intercept``), a weight floor keeps the Bernoulli variance away from
    zero, and a tiny Hessian jitter keeps the Newton system invertible under
    separation. Never raises: convergence is reported via ``converged``. An empty
    dataset returns the config default weights.
    """
    pred = config.predictive
    feature_names = tuple(pred.feature_names)
    d = len(feature_names)  # number of non-intercept features (theta, v, agent)

    n = len(dataset)
    if n == 0:
        # Graceful degradation: fall back to the configured default weights.
        return CalibrationParams(
            gamma=tuple(float(g) for g in pred.gamma),
            feature_names=feature_names,
            method=pred.calibration_method,
            sigma_reg=float(pred.sigma_reg),
            version=1,
            n_train=0,
            iters=0,
            converged=True,
        )

    thetas = np.array([row.theta for row in dataset], dtype=np.float64)
    vs = np.array([row.v for row in dataset], dtype=np.float64)
    agents = np.array([row.agent for row in dataset], dtype=np.float64)
    y = np.array([row.y for row in dataset], dtype=np.float64)
    ones = np.ones(n, dtype=np.float64)
    x_design: NDArray[np.float64] = np.column_stack([ones, thetas, vs, agents])

    lam = float(pred.ridge_lambda)
    penalty = np.full(d + 1, lam, dtype=np.float64)
    if not pred.penalize_intercept:
        penalty[0] = 0.0

    beta = np.zeros(d + 1, dtype=np.float64)
    jitter_eye = _HESS_JITTER * np.eye(d + 1, dtype=np.float64)
    max_iter = int(pred.max_iter)
    tol = float(pred.tol)
    fit_intercept = bool(pred.fit_intercept)

    iters = 0
    converged = False
    for it in range(max_iter):
        iters = it + 1
        eta: NDArray[np.float64] = x_design @ beta
        p: NDArray[np.float64] = np.asarray(sigmoid(eta), dtype=np.float64)
        w = np.maximum(p * (1.0 - p), _WEIGHT_FLOOR)
        # Penalised gradient of the negative log-likelihood.
        grad = x_design.T @ (p - y) + penalty * beta
        # Penalised, jittered Newton Hessian (X^T W X + diag(penalty) + jitter).
        hess = x_design.T @ (x_design * w[:, None]) + np.diag(penalty) + jitter_eye
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            break
        if not fit_intercept:
            step[0] = 0.0
        beta = beta - step
        if float(np.max(np.abs(step))) < tol:
            converged = True
            break

    gamma = tuple(float(b) for b in beta)
    return CalibrationParams(
        gamma=gamma,
        feature_names=feature_names,
        method=pred.calibration_method,
        sigma_reg=float(pred.sigma_reg),
        version=1,
        n_train=n,
        iters=iters,
        converged=converged,
    )


# --- prediction + errors-in-variables interval -------------------------------

def _apply_calibration(
    lin_scores: NDArray[np.float64],
    params: CalibrationParams,
) -> tuple[NDArray[np.float64], str]:
    """Map linear-predictor scores to calibrated probabilities.

    Returns ``(calibrated_probabilities, applied_method)``. ``applied_method`` is
    the method that actually ran (``"none"`` when the selected method has no
    fitted map, i.e. graceful fallback to the identity ``sigmoid``).
    """
    method = params.method
    if method == "platt" and params.platt is not None:
        return np.asarray(apply_platt(lin_scores, params.platt), dtype=np.float64), "platt"
    if method == "isotonic" and params.isotonic is not None:
        probs = np.asarray(sigmoid(lin_scores), dtype=np.float64)
        return np.asarray(apply_isotonic(probs, params.isotonic), dtype=np.float64), "isotonic"
    return np.asarray(sigmoid(lin_scores), dtype=np.float64), "none"


def predict(
    theta_hat: float,
    se_theta: float,
    v: float,
    agent: float,
    params: CalibrationParams,
    config: OperatorScoringConfig,
) -> Prediction:
    """Predict the criterion ``Y`` with an errors-in-variables 95% interval.

    ``lin = gamma0 + gamma1*theta + gamma2*v + gamma3*agent`` and
    ``Var(lin) = gamma1^2 * SE(theta)^2 + sigma_reg^2``. The point estimate and
    both interval endpoints are pushed through ``calib(sigmoid(.))``, so the
    interval is bounded to ``(0, 1)`` and asymmetric. ``params`` supplies the
    learned ``gamma`` / ``sigma_reg`` / calibration map; ``config.predictive.z``
    supplies the interval quantile.
    """
    z = float(config.predictive.z)
    gamma = np.asarray(params.gamma, dtype=np.float64)
    features = np.array([float(theta_hat), float(v), float(agent)], dtype=np.float64)

    lin = float(gamma[0] + gamma[1:] @ features)
    gamma_theta = float(gamma[1])  # coefficient on theta drives the EIV term
    var_lin = gamma_theta * gamma_theta * float(se_theta) * float(se_theta) + float(params.sigma_reg) ** 2
    se_lin = float(np.sqrt(var_lin))
    half = z * se_lin

    lin_scores = np.array([lin, lin - half, lin + half], dtype=np.float64)
    calibrated_probs, applied_method = _apply_calibration(lin_scores, params)
    y_hat = float(calibrated_probs[0])
    y_lower = float(calibrated_probs[1])
    y_upper = float(calibrated_probs[2])

    return Prediction(
        lin=lin,
        y_hat=y_hat,
        y_lower=y_lower,
        y_upper=y_upper,
        var_lin=var_lin,
        se_lin=se_lin,
        calibrated=applied_method != "none",
        calibration_method=applied_method,
    )


# --- Platt scaling: 1-D logistic on the score --------------------------------

def fit_platt(
    scores: ArrayLike,
    labels: ArrayLike,
    config: OperatorScoringConfig,
) -> PlattParams:
    """Fit ``sigmoid(A*score + B)`` by Newton on the (smoothed) cross-entropy.

    With ``config.predictive.platt_smoothing`` the Platt (1999) target smoothing
    ``t+ = (N+ + 1)/(N+ + 2)``, ``t- = 1/(N- + 2)`` is used (generalised to soft
    labels by mixing the two targets), which keeps the fit finite under perfect
    separation. Never raises; returns the last iterate on non-convergence.
    """
    pred = config.predictive
    x = np.asarray(scores, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.float64).ravel()
    n = x.size
    if n == 0:
        return PlattParams(A=0.0, B=0.0)

    if pred.platt_smoothing:
        n_pos = float(np.sum(y))
        n_neg = float(n) - n_pos
        t_pos = (n_pos + 1.0) / (n_pos + 2.0)
        t_neg = 1.0 / (n_neg + 2.0)
        target = y * t_pos + (1.0 - y) * t_neg
    else:
        target = y

    a_coef = 0.0
    b_coef = 0.0
    max_iter = int(pred.max_iter)
    tol = float(pred.tol)
    for _ in range(max_iter):
        p = np.asarray(sigmoid(a_coef * x + b_coef), dtype=np.float64)
        resid = p - target
        grad_a = float(np.sum(resid * x))
        grad_b = float(np.sum(resid))
        w = np.maximum(p * (1.0 - p), _WEIGHT_FLOOR)
        h_aa = float(np.sum(w * x * x)) + _HESS_JITTER
        h_ab = float(np.sum(w * x))
        h_bb = float(np.sum(w)) + _HESS_JITTER
        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-300:
            break
        step_a = (h_bb * grad_a - h_ab * grad_b) / det
        step_b = (-h_ab * grad_a + h_aa * grad_b) / det
        a_coef -= step_a
        b_coef -= step_b
        if max(abs(step_a), abs(step_b)) < tol:
            break

    return PlattParams(A=float(a_coef), B=float(b_coef))


def apply_platt(
    scores: ArrayLike,
    params: PlattParams,
) -> float | NDArray[np.float64]:
    """Apply Platt scaling ``sigmoid(A*score + B)`` (scalar in -> float out)."""
    arr = np.asarray(scores, dtype=np.float64)
    return sigmoid(params.A * arr + params.B)


# --- isotonic regression: pure-numpy PAVA ------------------------------------

def _pava(y: NDArray[np.float64], w: NDArray[np.float64]) -> NDArray[np.float64]:
    """Pool-adjacent-violators: least-squares non-decreasing fit to ``y``.

    ``y`` and ``w`` are aligned and already sorted by the covariate. Returns a
    non-decreasing array of the same length (the fitted value per input point).
    """
    values: list[float] = []
    weights: list[float] = []
    sizes: list[int] = []
    for yi, wi in zip(y.tolist(), w.tolist(), strict=True):
        values.append(float(yi))
        weights.append(float(wi))
        sizes.append(1)
        # Merge while the last block violates monotonicity with its predecessor.
        while len(values) > 1 and values[-2] > values[-1]:
            merged_w = weights[-2] + weights[-1]
            merged_val = (values[-2] * weights[-2] + values[-1] * weights[-1]) / merged_w
            merged_size = sizes[-2] + sizes[-1]
            values.pop()
            weights.pop()
            sizes.pop()
            values[-1] = merged_val
            weights[-1] = merged_w
            sizes[-1] = merged_size

    fitted: list[float] = []
    for val, size in zip(values, sizes, strict=True):
        fitted.extend([val] * size)
    return np.array(fitted, dtype=np.float64)


def fit_isotonic(
    scores: ArrayLike,
    labels: ArrayLike,
    weights: ArrayLike | None = None,
    *,
    interp: str = "linear",
) -> IsotonicParams:
    """Fit a monotone map by PAVA over ``(score, label)`` sorted by ``score``.

    Returns the fitted knots ``(x, y)`` (``x`` = sorted scores, ``y`` = the
    non-decreasing PAVA fit) to be applied via :func:`apply_isotonic`. Ties in
    ``score`` are averaged so the stored knots are strictly increasing in ``x``.
    """
    x = np.asarray(scores, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.float64).ravel()
    n = x.size
    if n == 0:
        return IsotonicParams(x=(), y=(), interp=interp)
    if weights is None:
        w = np.ones(n, dtype=np.float64)
    else:
        w = np.asarray(weights, dtype=np.float64).ravel()

    order = np.argsort(x, kind="stable")
    xs = x[order]
    ys = y[order]
    ws = w[order]
    fitted = _pava(ys, ws)

    # Collapse tied x-values (weighted mean of their fitted values) so the knots
    # are strictly increasing -- required for a well-defined np.interp map.
    knot_x: list[float] = []
    knot_y: list[float] = []
    i = 0
    while i < n:
        j = i
        acc_wy = 0.0
        acc_w = 0.0
        while j < n and xs[j] == xs[i]:
            acc_wy += fitted[j] * ws[j]
            acc_w += ws[j]
            j += 1
        knot_x.append(float(xs[i]))
        knot_y.append(float(acc_wy / acc_w) if acc_w > 0 else float(fitted[i]))
        i = j

    return IsotonicParams(x=tuple(knot_x), y=tuple(knot_y), interp=interp)


def apply_isotonic(
    scores: ArrayLike,
    params: IsotonicParams,
) -> float | NDArray[np.float64]:
    """Apply an isotonic map (``np.interp`` for ``"linear"``, step for ``"previous"``).

    Queries outside the knot range clamp to the nearest endpoint. Scalar input
    returns a ``float``.
    """
    arr = np.asarray(scores, dtype=np.float64)
    xp = np.asarray(params.x, dtype=np.float64)
    yp = np.asarray(params.y, dtype=np.float64)
    if xp.size == 0:
        # No fitted knots: identity fallback.
        return float(arr) if arr.ndim == 0 else arr

    if params.interp == "previous":
        idx = np.searchsorted(xp, arr, side="right") - 1
        idx = np.clip(idx, 0, yp.size - 1)
        out: NDArray[np.float64] = yp[idx]
    else:
        out = np.interp(arr, xp, yp)

    if arr.ndim == 0:
        return float(out)
    return out
