"""Numeric leaf utilities for the operator scoring core.

Framework-free: this module imports only the standard library and numpy. It is
the single sanctioned source of the sigmoid/logit primitives every layer shares
and the *only* entropy source in the core, the injected :class:`SeededRNG`
(wrapping ``numpy.random.default_rng``). No ``time``/``random``/``secrets``/
``datetime``/network module is imported anywhere in the core, so results are
fully reproducible under a fixed seed.
"""
from __future__ import annotations

from typing import overload

import numpy as np
from numpy.typing import ArrayLike, NDArray

# Clip the sigmoid argument to this magnitude before exponentiating. exp(500) is
# ~1.4e217 (well inside float64 range), so clipping here keeps sigmoid
# overflow-free without perturbing any in-range value: for |x| <= 500 the result
# is bit-identical to the naive ``1 / (1 + exp(-x))``.
SIGMOID_CLIP: float = 500.0


@overload
def sigmoid(x: float) -> float: ...
@overload
def sigmoid(x: NDArray[np.float64]) -> NDArray[np.float64]: ...


def sigmoid(x: ArrayLike) -> float | NDArray[np.float64]:
    """Logistic sigmoid, overflow-free.

    The argument is clipped to ``+/-SIGMOID_CLIP`` so ``exp`` never overflows;
    within that band the value is bit-identical to ``1 / (1 + exp(-x))``.
    ``sigmoid(1e6) == 1.0`` and ``sigmoid(-1e6)`` underflows cleanly to 0-ish,
    both without a numpy warning. Accepts scalars or arrays and returns the
    matching shape (a Python ``float`` for scalar input).
    """
    arr = np.asarray(x, dtype=np.float64)
    clipped = np.clip(arr, -SIGMOID_CLIP, SIGMOID_CLIP)
    out = 1.0 / (1.0 + np.exp(-clipped))
    if arr.ndim == 0:
        return float(out)
    return out


def logit(p: ArrayLike, eps: float = 1e-12) -> float | NDArray[np.float64]:
    """Inverse sigmoid ``log(p / (1 - p))``.

    ``p`` is clipped into ``[eps, 1 - eps]`` so the result stays finite at the
    boundary. Returns a Python ``float`` for scalar input.
    """
    arr = np.asarray(p, dtype=np.float64)
    clipped = np.clip(arr, eps, 1.0 - eps)
    out = np.log(clipped / (1.0 - clipped))
    if arr.ndim == 0:
        return float(out)
    return out


def safe_log(x: ArrayLike, eps: float = 1e-12) -> float | NDArray[np.float64]:
    """``log(x)`` with the argument floored at ``eps`` to avoid ``log(0) = -inf``."""
    arr = np.asarray(x, dtype=np.float64)
    out: NDArray[np.float64] = np.log(np.maximum(arr, eps))
    if arr.ndim == 0:
        return float(out)
    return out


def clip01(x: ArrayLike) -> float | NDArray[np.float64]:
    """Clip into the closed unit interval ``[0, 1]``."""
    arr = np.asarray(x, dtype=np.float64)
    out = np.clip(arr, 0.0, 1.0)
    if arr.ndim == 0:
        return float(out)
    return out


class SeededRNG:
    """Deterministic entropy source for the core.

    Thin wrapper over ``numpy.random.default_rng`` so the whole core takes its
    randomness from one injected, seedable object (no module-level ``random``).
    """

    def __init__(self, seed: int) -> None:
        self._seed = int(seed)
        self._rng = np.random.default_rng(self._seed)

    @property
    def seed(self) -> int:
        return self._seed

    def generator(self) -> np.random.Generator:
        """Return the underlying numpy ``Generator`` for direct sampling."""
        return self._rng

    def normal(
        self,
        loc: float = 0.0,
        scale: float = 1.0,
        size: int | tuple[int, ...] | None = None,
    ) -> float | NDArray[np.float64]:
        return self._rng.normal(loc=loc, scale=scale, size=size)

    def uniform(
        self,
        low: float = 0.0,
        high: float = 1.0,
        size: int | tuple[int, ...] | None = None,
    ) -> float | NDArray[np.float64]:
        return self._rng.uniform(low=low, high=high, size=size)

    def spawn(self, n: int) -> list[SeededRNG]:
        """Deterministically derive ``n`` independent child RNGs from this seed."""
        children = np.random.SeedSequence(self._seed).spawn(int(n))
        return [
            SeededRNG(int(child.generate_state(1, dtype=np.uint32)[0]))
            for child in children
        ]
