"""libSQL adapter for the operator scoring core (OUTSIDE the framework-free core).

This module is the *only* place that knows both the numeric core
(``app.operator_scoring``) and the libSQL persistence layer
(``app.core.database``); the core never imports this file. It provides:

* :class:`LibSQLItemRepository` / :class:`LibSQLCalibrationRepository` -- concrete
  implementations of the core ``ItemRepository`` / ``CalibrationRepository``
  Protocols over the ``operator_item_params`` / ``operator_calibration`` tables
  added by migration ``037``.
* :func:`operator_baseline_lift` -- the live-path Layer-E badge. Returns ``None``
  when the challenge has no ``operator_item_params`` row so the engine cleanly
  falls back to its legacy static ``ai_baseline`` badge.
* :func:`recompute_user_ability` -- re-fits a developer's Layer-D ability from the
  full-precision ``operator_l``/``operator_s`` stored on their best submission per
  challenge. Returns ``None`` below one usable item.

Config is read via ``resolve_config(getattr(settings, "OPERATOR_SCORING_CONFIG",
None))`` so no ``Settings`` change is required; a missing attribute yields the
default (oracle) config.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.operator_scoring import (
    AbilityEstimate,
    BaselineStats,
    CalibrationParams,
    Item,
    ItemObservation,
    OperatorScoringConfig,
    SeededRNG,
    compute_lift,
    fit_ability,
    resolve_config,
)
from app.operator_scoring.irt import IrtError
from app.operator_scoring.itembank import ItemValidationError

logger = logging.getLogger(__name__)


def _resolve_config() -> OperatorScoringConfig:
    """Resolve the operator-scoring config from settings (missing attr -> defaults)."""
    return resolve_config(getattr(settings, "OPERATOR_SCORING_CONFIG", None))


# ── item bank repository ──────────────────────────────────────────────────────

def _item_from_row(row: dict[str, Any]) -> Item | None:
    """Build a core :class:`Item` from an ``operator_item_params`` row.

    Returns ``None`` when the row is too incomplete/ill-posed to form a valid
    item (missing discrimination/difficulty, ``a <= 0``, degenerate ceiling, ...)
    so the live path degrades gracefully instead of raising.
    """
    a = row.get("a")
    b = row.get("b")
    if a is None or b is None:
        return None

    vec_raw = row.get("discrimination_vec")
    a_vec: tuple[float, ...] | None = None
    if vec_raw:
        try:
            parsed = json.loads(vec_raw)
            if isinstance(parsed, list) and parsed:
                a_vec = tuple(float(x) for x in parsed)
        except (ValueError, TypeError):
            a_vec = None

    m_raw = row.get("baseline_m")
    try:
        return Item(
            id=str(row["challenge_id"]),
            a=float(a),
            b=float(b),
            s=None if row.get("s") is None else float(row["s"]),
            mu0=None if row.get("mu_baseline") is None else float(row["mu_baseline"]),
            sigma0=None if row.get("sigma_baseline") is None else float(row["sigma_baseline"]),
            M=None if m_raw is None else int(m_raw),
            ceiling=None if row.get("ceiling") is None else float(row["ceiling"]),
            sigma_intrinsic=None
            if row.get("sigma_intrinsic") is None
            else float(row["sigma_intrinsic"]),
            a_vec=a_vec,
        )
    except (ItemValidationError, ValueError, TypeError):
        return None


class LibSQLItemRepository:
    """Core ``ItemRepository`` backed by the ``operator_item_params`` table."""

    def get(self, item_id: str) -> Item | None:
        row = fetch_one(
            "SELECT * FROM operator_item_params WHERE challenge_id = ?",
            (item_id,),
        )
        if row is None:
            return None
        return _item_from_row(row)

    def list(self) -> list[Item]:
        rows = fetch_all("SELECT * FROM operator_item_params")
        items: list[Item] = []
        for row in rows:
            item = _item_from_row(row)
            if item is not None:
                items.append(item)
        return items

    def upsert(self, item: Item) -> None:
        vec = json.dumps(list(item.a_vec)) if item.a_vec is not None else None
        execute(
            """INSERT INTO operator_item_params
                  (challenge_id, a, b, s, mu_baseline, sigma_baseline, baseline_m,
                   ceiling, sigma_intrinsic, discrimination_vec, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(challenge_id) DO UPDATE SET
                  a = excluded.a, b = excluded.b, s = excluded.s,
                  mu_baseline = excluded.mu_baseline,
                  sigma_baseline = excluded.sigma_baseline,
                  baseline_m = excluded.baseline_m,
                  ceiling = excluded.ceiling,
                  sigma_intrinsic = excluded.sigma_intrinsic,
                  discrimination_vec = excluded.discrimination_vec,
                  updated_at = excluded.updated_at""",
            (
                item.id, item.a, item.b, item.s, item.mu0, item.sigma0, item.M,
                item.ceiling, item.sigma_intrinsic, vec,
            ),
        )


# ── calibration repository ────────────────────────────────────────────────────

class LibSQLCalibrationRepository:
    """Core ``CalibrationRepository`` backed by the ``operator_calibration`` table.

    The store is single-keyed (``key``); ``version`` selection is ignored because
    the table keeps one live record per key. ``get``/``latest`` both return that
    record. The full unified :class:`CalibrationParams` is round-tripped through
    the ``calibration_params`` JSON column so Platt/Isotonic sub-records survive.
    """

    def __init__(self, key: str = "live") -> None:
        self._key = key

    def _row(self) -> dict[str, Any] | None:
        return fetch_one(
            "SELECT * FROM operator_calibration WHERE key = ?",
            (self._key,),
        )

    def get(self, version: int | None = None) -> CalibrationParams | None:
        return self.latest()

    def latest(self) -> CalibrationParams | None:
        row = self._row()
        if row is None:
            return None
        params_raw = row.get("calibration_params")
        if params_raw:
            try:
                from app.operator_scoring.calibration_store import calibration_from_dict
                data = json.loads(params_raw)
                if isinstance(data, dict):
                    return calibration_from_dict(data)
            except (ValueError, TypeError, KeyError):
                pass
        gammas = [
            row.get("gamma0"), row.get("gamma1"), row.get("gamma2"), row.get("gamma3"),
        ]
        gamma = tuple(float(g) for g in gammas if g is not None)
        if len(gamma) < 2:
            return None
        feature_names = ("theta", "v", "agent")[: len(gamma) - 1]
        try:
            return CalibrationParams(
                gamma=gamma,
                feature_names=feature_names,
                method=str(row.get("calibration_method") or "none"),
                sigma_reg=float(row.get("sigma_reg") or 0.05),
            )
        except (ValueError, TypeError):
            return None

    def save(self, params: CalibrationParams) -> None:
        gamma = list(params.gamma) + [None, None, None, None]
        execute(
            """INSERT INTO operator_calibration
                  (key, gamma0, gamma1, gamma2, gamma3, sigma_reg,
                   calibration_method, calibration_params, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                  gamma0 = excluded.gamma0, gamma1 = excluded.gamma1,
                  gamma2 = excluded.gamma2, gamma3 = excluded.gamma3,
                  sigma_reg = excluded.sigma_reg,
                  calibration_method = excluded.calibration_method,
                  calibration_params = excluded.calibration_params,
                  updated_at = excluded.updated_at""",
            (
                self._key, gamma[0], gamma[1], gamma[2], gamma[3],
                params.sigma_reg, params.method, json.dumps(params.to_json()),
            ),
        )


# ── Layer-E live badge ────────────────────────────────────────────────────────

@dataclass
class OperatorLiftBadge:
    """The operator (Layer-E) baseline-lift badge for a submission.

    ``L``/``s`` are the *full-precision* Layer-E outputs (stashed on the
    submission and later re-fed into Layer D); ``to_badge_dict`` rounds display
    values only.
    """

    beat: bool
    delta: float
    L: float
    s: float
    mu_baseline: float
    ceiling: float

    def to_badge_dict(self, decimals: int = 4) -> dict[str, Any]:
        return {
            "beat": self.beat,
            "delta": self.delta,
            "L": round(self.L, decimals),
            "s": round(self.s, decimals),
            "mu_baseline": round(self.mu_baseline, decimals),
            "ceiling": round(self.ceiling, decimals),
            "source": "operator",
        }


def _lift_config_for_item(item: Item) -> OperatorScoringConfig:
    """Base config with Layer-E defaults overridden by the item's DB calibration.

    Missing item fields simply keep the global defaults, so a partially
    calibrated challenge still resolves a well-posed baseline.
    """
    config = _resolve_config()
    lift = config.lift
    if item.mu0 is not None:
        lift.default_mu0 = float(item.mu0)
    if item.sigma0 is not None:
        lift.default_sigma0 = float(item.sigma0)
    if item.M is not None:
        lift.default_M = int(item.M)
    if item.ceiling is not None:
        lift.default_ceiling = float(item.ceiling)
    if item.sigma_intrinsic is not None:
        lift.sigma_intrinsic = float(item.sigma_intrinsic)
    return config


def operator_baseline_lift(
    challenge_id: str,
    outcome_norm: float,
    ai_baseline: float | None,
    repo: LibSQLItemRepository | None = None,
) -> OperatorLiftBadge | None:
    """Compute the operator (Layer-E) baseline-lift badge for a challenge.

    Looks up ``operator_item_params`` for ``challenge_id`` and computes the
    normalized lift ``L`` (+ measurement SD ``s``) of the graded outcome
    ``outcome_norm in [0, 1]`` over the challenge's solo-AI baseline. Returns
    ``None`` when there is no row (or no usable baseline), so the engine falls
    back to the legacy static ``ai_baseline`` badge. ``ai_baseline`` is accepted
    for API parity with that legacy path.
    """
    repo = repo if repo is not None else LibSQLItemRepository()
    try:
        item = repo.get(challenge_id)
    except Exception:
        logger.exception("Item lookup failed for challenge %s", challenge_id)
        return None
    if item is None or not item.has_baseline_stats:
        return None

    config = _lift_config_for_item(item)
    mu0 = float(item.mu0) if item.mu0 is not None else config.lift.default_mu0
    sigma0 = float(item.sigma0) if item.sigma0 is not None else config.lift.default_sigma0
    M = int(item.M) if item.M is not None else config.lift.default_M
    ceiling = float(item.ceiling) if item.ceiling is not None else config.lift.default_ceiling
    sigma_intrinsic = (
        float(item.sigma_intrinsic)
        if item.sigma_intrinsic is not None
        else config.lift.sigma_intrinsic
    )

    try:
        baseline = BaselineStats(mu0=mu0, sigma0=sigma0, M=M)
        lift = compute_lift(
            float(outcome_norm), baseline, ceiling, sigma_intrinsic, config
        )
    except Exception:
        logger.exception("Lift computation failed for challenge %s", challenge_id)
        return None

    o = float(outcome_norm)
    beat = o > mu0
    delta = round(max(0.0, (o - mu0) * 100.0), 2)
    return OperatorLiftBadge(
        beat=beat, delta=delta, L=lift.L, s=lift.s, mu_baseline=mu0, ceiling=ceiling
    )


# ── Layer-D live ability re-fit ───────────────────────────────────────────────

def recompute_user_ability(user_id: str) -> AbilityEstimate | None:
    """Re-fit a developer's Layer-D ability from their stored per-item lifts.

    Builds one :class:`ItemObservation` per challenge from the developer's
    best-scored submission that carries a full-precision ``operator_l``/
    ``operator_s`` (joined to the challenge's IRT ``a``/``b``), then runs
    ``fit_ability`` under a fixed seed. Returns ``None`` when fewer than one
    usable item exists.
    """
    rows = fetch_all(
        """SELECT s.challenge_id AS challenge_id,
                  s.operator_l   AS operator_l,
                  s.operator_s   AS operator_s,
                  p.a            AS a,
                  p.b            AS b
             FROM submissions s
             JOIN operator_item_params p ON p.challenge_id = s.challenge_id
            WHERE s.user_id = ?
              AND s.status = 'scored'
              AND s.operator_l IS NOT NULL
              AND s.score = (
                  SELECT MAX(s2.score) FROM submissions s2
                   WHERE s2.user_id = s.user_id
                     AND s2.challenge_id = s.challenge_id
                     AND s2.status = 'scored'
                     AND s2.operator_l IS NOT NULL
              )
            GROUP BY s.challenge_id""",
        (user_id,),
    )

    observations: list[ItemObservation] = []
    for row in rows:
        L = row.get("operator_l")
        s = row.get("operator_s")
        a = row.get("a")
        b = row.get("b")
        if L is None or s is None or a is None or b is None:
            continue
        try:
            sv = float(s)
            av = float(a)
            if not sv > 0 or av == 0:
                continue
            observations.append(
                ItemObservation(
                    L=float(L), a=av, b=float(b), s=sv,
                    item_id=str(row.get("challenge_id") or ""),
                )
            )
        except (ValueError, TypeError, IrtError):
            continue

    if len(observations) < 1:
        return None

    config = _resolve_config()
    # Fixed seed: ability estimation is analytic and reproducible run-to-run.
    _ = SeededRNG(int(config.rng_seed))
    return fit_ability(observations, config)
