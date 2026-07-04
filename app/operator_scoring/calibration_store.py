"""Layer-G predictive calibration record + its versioned store.

One :class:`CalibrationParams` is the *unified* Layer-G calibration record
(SCORING_DESIGN section 9): the learned re-weighting ``gamma`` plus its EIV
residual SD ``sigma_reg`` and an optional output-calibration map (Platt or
Isotonic). ``itembank.Item`` owns the IRT item calibration ``(a, b, s)``; this
module owns the predictive calibration.

Framework-free: stdlib only (``dataclasses`` + ``json``), numpy is not even
needed here. There is **no** ``time``/``datetime`` import: ``fitted_at`` is a
caller-supplied string so the core stays deterministic. ``to_json()`` serialises
at full precision (this is a persistence format, not a display rounding), so a
round-trip through :class:`JsonCalibrationRepository` is loss-free.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class CalibrationParamsError(ValueError):
    """Raised by :class:`CalibrationParams.__post_init__` on an invalid record."""


@dataclass(frozen=True)
class PlattParams:
    """1-D logistic output calibration ``sigma(A * score + B)``."""

    A: float
    B: float

    def to_json(self) -> dict[str, Any]:
        return {"A": self.A, "B": self.B}


@dataclass(frozen=True)
class IsotonicParams:
    """Monotone output calibration: a piecewise map applied via ``np.interp``.

    ``x`` are the (sorted) score knots and ``y`` the calibrated values. Both are
    normalised to tuples in ``__post_init__`` so a record built from JSON arrays
    compares equal to one built from Python tuples.
    """

    x: tuple[float, ...]
    y: tuple[float, ...]
    interp: str = "linear"

    def __post_init__(self) -> None:
        # Frozen dataclass: coerce sequences to tuples via object.__setattr__ so
        # JSON-loaded lists round-trip to equal records.
        object.__setattr__(self, "x", tuple(float(v) for v in self.x))
        object.__setattr__(self, "y", tuple(float(v) for v in self.y))

    def to_json(self) -> dict[str, Any]:
        return {"x": list(self.x), "y": list(self.y), "interp": self.interp}


@dataclass
class CalibrationParams:
    """The Layer-G predictive calibration record (unified per section 9/16)."""

    gamma: tuple[float, ...]
    feature_names: tuple[str, ...]
    method: str = "none"
    sigma_reg: float = 0.05
    platt: PlattParams | None = None
    isotonic: IsotonicParams | None = None
    version: int = 1
    n_train: int | None = None
    iters: int = 0
    converged: bool = True
    fitted_at: str | None = None  # caller-supplied; the core never calls time/datetime

    def __post_init__(self) -> None:
        # Normalise to tuples so records built from JSON arrays compare equal.
        object.__setattr__(self, "gamma", tuple(float(v) for v in self.gamma))
        object.__setattr__(self, "feature_names", tuple(str(v) for v in self.feature_names))
        if len(self.gamma) != len(self.feature_names) + 1:
            raise CalibrationParamsError(
                "CalibrationParams requires len(gamma) == len(feature_names) + 1 "
                f"(got {len(self.gamma)} vs {len(self.feature_names)} + 1)"
            )
        if self.sigma_reg < 0:
            raise CalibrationParamsError("CalibrationParams.sigma_reg must be >= 0")

    def to_json(self) -> dict[str, Any]:
        """Full-precision serialisation (persistence, not display rounding)."""
        return {
            "gamma": list(self.gamma),
            "feature_names": list(self.feature_names),
            "method": self.method,
            "sigma_reg": self.sigma_reg,
            "platt": self.platt.to_json() if self.platt is not None else None,
            "isotonic": self.isotonic.to_json() if self.isotonic is not None else None,
            "version": self.version,
            "n_train": self.n_train,
            "iters": self.iters,
            "converged": self.converged,
            "fitted_at": self.fitted_at,
        }


def calibration_from_dict(d: dict[str, Any]) -> CalibrationParams:
    """Reconstruct a :class:`CalibrationParams` from its ``to_json()`` dict.

    Normalises JSON arrays back into tuples and rebuilds the nested Platt /
    Isotonic sub-records so a store round-trip is loss-free.
    """
    platt_raw = d.get("platt")
    platt = (
        PlattParams(A=float(platt_raw["A"]), B=float(platt_raw["B"]))
        if isinstance(platt_raw, dict)
        else None
    )
    iso_raw = d.get("isotonic")
    isotonic = (
        IsotonicParams(
            x=tuple(float(v) for v in iso_raw.get("x", ())),
            y=tuple(float(v) for v in iso_raw.get("y", ())),
            interp=str(iso_raw.get("interp", "linear")),
        )
        if isinstance(iso_raw, dict)
        else None
    )
    n_train_raw = d.get("n_train")
    fitted_at_raw = d.get("fitted_at")
    return CalibrationParams(
        gamma=tuple(float(v) for v in d["gamma"]),
        feature_names=tuple(str(v) for v in d["feature_names"]),
        method=str(d.get("method", "none")),
        sigma_reg=float(d.get("sigma_reg", 0.05)),
        platt=platt,
        isotonic=isotonic,
        version=int(d.get("version", 1)),
        n_train=None if n_train_raw is None else int(n_train_raw),
        iters=int(d.get("iters", 0)),
        converged=bool(d.get("converged", True)),
        fitted_at=None if fitted_at_raw is None else str(fitted_at_raw),
    )


@runtime_checkable
class CalibrationRepository(Protocol):
    """Versioned store of Layer-G calibration records."""

    def get(self, version: int | None = None) -> CalibrationParams | None: ...
    def latest(self) -> CalibrationParams | None: ...
    def save(self, params: CalibrationParams) -> None: ...


class _BaseCalibrationRepository:
    """Shared version-indexed read logic for the concrete repositories."""

    _by_version: dict[int, CalibrationParams]

    def get(self, version: int | None = None) -> CalibrationParams | None:
        """Return the record for ``version``; ``None`` selects the latest."""
        if version is None:
            return self.latest()
        return self._by_version.get(version)

    def latest(self) -> CalibrationParams | None:
        """Return the highest-version record, or ``None`` when the store is empty."""
        if not self._by_version:
            return None
        return self._by_version[max(self._by_version)]


class InMemoryCalibrationRepository(_BaseCalibrationRepository):
    """Dict-backed store, keyed by ``params.version`` (higher version wins)."""

    def __init__(self) -> None:
        self._by_version = {}

    def save(self, params: CalibrationParams) -> None:
        self._by_version[params.version] = params


class JsonCalibrationRepository(_BaseCalibrationRepository):
    """Path-backed store: a JSON array of ``CalibrationParams.to_json()`` records.

    Loads on construction (missing/malformed file starts empty, never raises)
    and, when ``autosave`` is set, flushes on every :meth:`save`.
    """

    def __init__(self, path: str, autosave: bool = True) -> None:
        self._path = path
        self._autosave = autosave
        self._by_version = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        if not isinstance(data, list):
            return
        for entry in data:
            if not isinstance(entry, dict):
                continue
            try:
                params = calibration_from_dict(entry)
            except (KeyError, TypeError, ValueError):
                continue
            self._by_version[params.version] = params

    def _flush(self) -> None:
        payload = [self._by_version[v].to_json() for v in sorted(self._by_version)]
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

    def save(self, params: CalibrationParams) -> None:
        self._by_version[params.version] = params
        if self._autosave:
            self._flush()

    def flush(self) -> None:
        """Force a write of the current records to disk."""
        self._flush()
