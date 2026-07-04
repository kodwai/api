from __future__ import annotations

import pytest

from app.operator_scoring.calibration_store import (
    CalibrationParams,
    CalibrationParamsError,
    CalibrationRepository,
    InMemoryCalibrationRepository,
    IsotonicParams,
    JsonCalibrationRepository,
    PlattParams,
    calibration_from_dict,
)

# --- CalibrationParams validation --------------------------------------------

def test_valid_params_defaults():
    p = CalibrationParams(gamma=(-0.80, 1.10, 0.60, -0.15), feature_names=("theta", "v", "agent"))
    assert p.method == "none"
    assert p.sigma_reg == 0.05
    assert p.version == 1
    assert p.iters == 0
    assert p.converged is True
    assert p.platt is None
    assert p.isotonic is None
    assert p.fitted_at is None
    assert p.n_train is None


def test_gamma_feature_length_must_match():
    # len(gamma) must equal len(feature_names) + 1.
    with pytest.raises(CalibrationParamsError):
        CalibrationParams(gamma=(-0.8, 1.1, 0.6), feature_names=("theta", "v", "agent"))
    with pytest.raises(CalibrationParamsError):
        CalibrationParams(gamma=(-0.8, 1.1, 0.6, -0.15, 0.2), feature_names=("theta", "v", "agent"))
    # CalibrationParamsError is a ValueError subclass.
    with pytest.raises(ValueError):
        CalibrationParams(gamma=(1.0,), feature_names=("theta", "v"))


def test_sigma_reg_must_be_nonnegative():
    with pytest.raises(CalibrationParamsError):
        CalibrationParams(
            gamma=(-0.8, 1.1, 0.6, -0.15),
            feature_names=("theta", "v", "agent"),
            sigma_reg=-0.01,
        )
    # zero is allowed.
    ok = CalibrationParams(
        gamma=(-0.8, 1.1, 0.6, -0.15),
        feature_names=("theta", "v", "agent"),
        sigma_reg=0.0,
    )
    assert ok.sigma_reg == 0.0


def test_lists_are_coerced_to_tuples():
    # A record built from JSON-style lists normalises to tuples for equality.
    p = CalibrationParams(gamma=[1.0, 2.0], feature_names=["theta"])  # type: ignore[arg-type]
    assert p.gamma == (1.0, 2.0)
    assert isinstance(p.gamma, tuple)
    assert isinstance(p.feature_names, tuple)


def test_isotonic_params_coerce_to_tuples():
    iso = IsotonicParams(x=[0.0, 0.5, 1.0], y=[0.1, 0.4, 0.9])  # type: ignore[arg-type]
    assert iso.x == (0.0, 0.5, 1.0)
    assert isinstance(iso.x, tuple)
    assert isinstance(iso.y, tuple)
    assert iso.interp == "linear"


# --- versioned repository semantics (InMemory) -------------------------------

def _params(version: int, sigma_reg: float = 0.05) -> CalibrationParams:
    return CalibrationParams(
        gamma=(-0.80, 1.10, 0.60, -0.15),
        feature_names=("theta", "v", "agent"),
        sigma_reg=sigma_reg,
        version=version,
    )


def test_inmemory_is_a_calibration_repository():
    repo = InMemoryCalibrationRepository()
    assert isinstance(repo, CalibrationRepository)


def test_inmemory_empty_returns_none():
    repo = InMemoryCalibrationRepository()
    assert repo.latest() is None
    assert repo.get() is None
    assert repo.get(1) is None


def test_inmemory_save_get_latest():
    repo = InMemoryCalibrationRepository()
    v1 = _params(1, sigma_reg=0.05)
    v2 = _params(2, sigma_reg=0.07)
    repo.save(v1)
    repo.save(v2)
    assert repo.get(1) == v1
    assert repo.get(2) == v2
    assert repo.latest() == v2
    assert repo.get() == v2          # version=None selects latest
    assert repo.get(99) is None      # unknown version


def test_inmemory_latest_ignores_insertion_order():
    # latest() is by highest version, not insertion order.
    repo = InMemoryCalibrationRepository()
    repo.save(_params(5))
    repo.save(_params(2))
    assert repo.latest().version == 5


def test_inmemory_save_same_version_overwrites():
    repo = InMemoryCalibrationRepository()
    repo.save(_params(1, sigma_reg=0.05))
    repo.save(_params(1, sigma_reg=0.09))
    got = repo.get(1)
    assert got is not None
    assert got.sigma_reg == 0.09


# --- JSON round-trip with platt + isotonic arrays ----------------------------

def _rich_params(version: int) -> CalibrationParams:
    return CalibrationParams(
        gamma=(-0.80, 1.10, 0.60, -0.15),
        feature_names=("theta", "v", "agent"),
        method="isotonic",
        sigma_reg=0.05,
        platt=PlattParams(A=1.2345, B=-0.6789),
        isotonic=IsotonicParams(
            x=(0.0, 0.25, 0.5, 0.75, 1.0),
            y=(0.02, 0.19, 0.51, 0.83, 0.98),
            interp="linear",
        ),
        version=version,
        n_train=128,
        iters=7,
        converged=True,
        fitted_at="2026-07-04T00:00:00Z",
    )


def test_calibration_params_dict_roundtrip():
    p = _rich_params(3)
    assert calibration_from_dict(p.to_json()) == p


def test_json_repo_roundtrip_via_tmp_path(tmp_path):
    path = str(tmp_path / "calibration.json")
    repo = JsonCalibrationRepository(path)
    v1 = _rich_params(1)
    v2 = _rich_params(2)
    repo.save(v1)
    repo.save(v2)

    # A brand-new repo over the same file reloads both records losslessly.
    reloaded = JsonCalibrationRepository(path)
    assert reloaded.get(1) == v1
    assert reloaded.latest() == v2
    got1 = reloaded.get(1)
    got2 = reloaded.get(2)
    assert got1 is not None and got1.platt == v1.platt
    assert got2 is not None and got2.isotonic == v2.isotonic
    # Full precision survives the round-trip (no display rounding on persistence).
    assert got1.platt is not None
    assert got1.platt.A == 1.2345
    assert got2.isotonic is not None
    assert got2.isotonic.x == (0.0, 0.25, 0.5, 0.75, 1.0)


def test_json_repo_missing_file_starts_empty():
    # Pointing at a non-existent path is not an error; the store is just empty.
    repo = JsonCalibrationRepository("/nonexistent/dir/calibration.json", autosave=False)
    assert repo.latest() is None
    assert repo.get(1) is None


def test_json_repo_malformed_file_starts_empty(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not valid json{", encoding="utf-8")
    repo = JsonCalibrationRepository(str(path), autosave=False)
    assert repo.latest() is None


def test_json_repo_no_autosave_does_not_write(tmp_path):
    path = tmp_path / "calibration.json"
    repo = JsonCalibrationRepository(str(path), autosave=False)
    repo.save(_rich_params(1))
    assert not path.exists()          # nothing flushed
    repo.flush()
    assert path.exists()              # explicit flush writes
    assert JsonCalibrationRepository(str(path)).latest() == _rich_params(1)
