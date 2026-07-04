"""Hermetic fixtures + deterministic helpers for the operator scoring core suite.

The autouse ``fresh_db`` here is a NO-OP that *shadows* the parent
``api/tests/conftest.py`` autouse DB/FastAPI fixture, so pure-core tests never
boot the app or touch a database. The helper functions give property-style tests
a single seeded generator and a tolerance comparator.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

# Shared default seed for the core test suite (today's date, YYYYMMDD).
DEFAULT_SEED = 20260704


@pytest.fixture(autouse=True)
def fresh_db():  # type: ignore[no-untyped-def]
    """Shadow the parent autouse DB fixture with a no-op so core tests stay hermetic."""
    yield


def make_rng(seed: int = DEFAULT_SEED) -> np.random.Generator:
    """Return a fresh, deterministically seeded numpy Generator."""
    return np.random.default_rng(seed)


def given_seeded[T](
    n: int,
    sampler: Callable[[np.random.Generator], T],
    *,
    seed: int = DEFAULT_SEED,
) -> list[T]:
    """Draw ``n`` deterministic cases from one seeded generator.

    ``sampler`` is called with the shared generator and returns one case; the
    drawn cases are returned in order so a property test can iterate them (and
    print the offending case on failure).
    """
    rng = np.random.default_rng(seed)
    return [sampler(rng) for _ in range(n)]


def approx(actual: float, expected: float, tol: float = 1e-3) -> bool:
    """True when ``actual`` is within absolute tolerance ``tol`` of ``expected``."""
    return abs(float(actual) - float(expected)) <= tol
