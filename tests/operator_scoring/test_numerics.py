from __future__ import annotations

import warnings

import numpy as np

from app.operator_scoring.numerics import (
    SIGMOID_CLIP,
    SeededRNG,
    clip01,
    logit,
    safe_log,
    sigmoid,
)


def test_sigmoid_scalar_and_array_agree():
    # Scalar input returns a Python float equal to the array element.
    assert isinstance(sigmoid(0.5), float)
    xs = np.array([-2.0, 0.0, 0.5, 1.0, 3.3])
    arr = sigmoid(xs)
    assert isinstance(arr, np.ndarray)
    for i, x in enumerate(xs):
        assert sigmoid(float(x)) == arr[i]


def test_sigmoid_midpoint_and_range():
    assert sigmoid(0.0) == 0.5
    vals = sigmoid(np.linspace(-10.0, 10.0, 101))
    assert np.all(vals > 0.0)
    assert np.all(vals < 1.0)


def test_sigmoid_overflow_saturates_without_warning():
    # No numpy overflow/underflow warning may fire, and the value saturates.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert sigmoid(1e6) == 1.0
        assert sigmoid(-1e6) >= 0.0
        assert sigmoid(-1e6) < 1e-100
        big = sigmoid(np.array([1e6, -1e6, 1e300, -1e300]))
    assert big[0] == 1.0
    assert big[2] == 1.0
    assert np.all(np.isfinite(big))
    # Clipping at +/-SIGMOID_CLIP: anything past the clip is identical to the clip.
    assert sigmoid(1e6) == sigmoid(SIGMOID_CLIP)
    assert sigmoid(-1e6) == sigmoid(-SIGMOID_CLIP)


def test_sigmoid_bit_identical_in_range():
    # Within the clip band the value is exactly the naive 1/(1+exp(-x)).
    xs = np.linspace(-SIGMOID_CLIP, SIGMOID_CLIP, 4001)
    naive = 1.0 / (1.0 + np.exp(-xs))
    assert np.array_equal(sigmoid(xs), naive)


def test_sigmoid_symmetry():
    # sigmoid(-x) + sigmoid(x) == 1, to within floating-point (<= 1 ULP).
    xs = np.linspace(-40.0, 40.0, 8001)
    total = sigmoid(-xs) + sigmoid(xs)
    assert np.allclose(total, 1.0, rtol=0.0, atol=1e-12)
    assert sigmoid(-0.0) + sigmoid(0.0) == 1.0


def test_logit_sigmoid_roundtrip():
    # logit inverts sigmoid across [-30, 30]; results stay finite throughout.
    xs = np.linspace(-30.0, 30.0, 121)
    rt = logit(sigmoid(xs))
    assert np.all(np.isfinite(rt))
    # The 1e-12 eps floor only saturates beyond ~27.6; the interior inverts tightly.
    band = np.abs(xs) <= 25.0
    assert np.allclose(rt[band], xs[band], rtol=0.0, atol=1e-4)
    assert isinstance(logit(0.5), float)
    assert abs(logit(0.5)) < 1e-12


def test_logit_clips_extremes():
    # p at/beyond {0, 1} is clipped by eps, so the result is finite (never +/-inf).
    assert np.isfinite(logit(0.0))
    assert np.isfinite(logit(1.0))
    assert logit(0.0) < 0.0
    assert logit(1.0) > 0.0


def test_safe_log_floors_at_eps():
    assert np.isfinite(safe_log(0.0))
    assert safe_log(0.0) == np.log(1e-12)
    assert safe_log(np.e) == 1.0


def test_clip01():
    assert clip01(-0.3) == 0.0
    assert clip01(1.7) == 1.0
    assert clip01(0.42) == 0.42
    assert np.array_equal(clip01(np.array([-1.0, 0.5, 2.0])), np.array([0.0, 0.5, 1.0]))


def test_seeded_rng_reproducible():
    a = SeededRNG(42)
    b = SeededRNG(42)
    assert np.array_equal(a.normal(size=5), b.normal(size=5))
    assert np.array_equal(a.uniform(size=5), b.uniform(size=5))
    # Same seed => same generator stream; a different seed diverges.
    c = SeededRNG(43)
    assert not np.array_equal(SeededRNG(42).normal(size=5), c.normal(size=5))


def test_seeded_rng_spawn_deterministic():
    children_a = SeededRNG(7).spawn(3)
    children_b = SeededRNG(7).spawn(3)
    assert [c.seed for c in children_a] == [c.seed for c in children_b]
    # Children are distinct streams from the parent and each other.
    seeds = [c.seed for c in children_a]
    assert len(set(seeds)) == 3
    draws = [c.normal(size=3) for c in children_a]
    assert not np.array_equal(draws[0], draws[1])
