"""Configuration tree for the operator scoring core.

One :class:`OperatorScoringConfig` holds every tunable for Layers B/E/D/G. It is
loaded by :func:`resolve_config`, which mirrors
``app/services/scoring/config.py::resolve_config``: it accepts a JSON string, a
dict, or ``None``; malformed input falls back to defaults and never raises;
unknown keys are ignored. Range validation lives in each dataclass'
``__post_init__``. The defaults here *are* the acceptance oracle.

Framework-free: stdlib only (``dataclasses`` + ``json``), no pydantic/fastapi.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Any

_WEIGHT_POLICIES = ("normalize", "strict")
_ON_CHECK_ERRORS = ("zero", "skip", "fail")
_FLAKINESS_METRICS = ("aggregate_stdev", "weighted_check_stdev")
_CALIBRATION_METHODS = ("none", "platt", "isotonic")
_BACKENDS = ("memory", "json")


class OperatorScoringConfigError(ValueError):
    """Raised by a config dataclass' ``__post_init__`` on an out-of-range value."""


@dataclass
class MutationConfig:
    kill_rate_threshold: float = 0.80     # gate_passed = kill_rate >= this
    kill_outcome_threshold: float = 1.0   # mutant killed iff O_mut < this
    replays: int = 1                      # replays when grading each mutant
    require_reference_pass: bool = True   # grade unmutated reference first
    reference_pass_threshold: float = 1.0  # reference must reach this or raise
    # Sub-check kinds the suite MUST carry non-zero weight on for the oracle to
    # count as "strong" (closes the weak-oracle gap: a functional-only suite with
    # functional-only mutations otherwise passes the kill-rate gate at 100% with
    # zero adversarial/security coverage). Empty => coverage not enforced.
    required_kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.replays < 1:
            raise OperatorScoringConfigError("MutationConfig.replays must be >= 1")
        if not 0.0 <= self.kill_rate_threshold <= 1.0:
            raise OperatorScoringConfigError(
                "MutationConfig.kill_rate_threshold must be in [0, 1]"
            )


@dataclass
class GraderConfig:
    replays: int = 3                      # R build/test replays for flakiness
    weight_policy: str = "normalize"      # "normalize" | "strict"
    weight_sum_tolerance: float = 1e-6    # strict policy tolerance on |sum(w) - 1|
    on_check_error: str = "zero"          # "zero" | "skip" | "fail"
    flakiness_metric: str = "aggregate_stdev"  # | "weighted_check_stdev"
    flakiness_penalty_weight: float = 1.0  # O = clip(mean - w*phi, 0, 1); 0 disables
    flakiness_threshold: float = 0.05     # phi / sd_k above this => flaky
    allowed_kinds: tuple[str, ...] = (
        "functional",
        "edge_adversarial",
        "property_invariants",
        "performance",
        "security_fuzz",
    )
    display_dp: int = 4                   # to_json() rounding ONLY
    mutation: MutationConfig = field(default_factory=MutationConfig)

    def __post_init__(self) -> None:
        if self.replays < 1:
            raise OperatorScoringConfigError("GraderConfig.replays must be >= 1")
        if self.weight_policy not in _WEIGHT_POLICIES:
            raise OperatorScoringConfigError(
                f"GraderConfig.weight_policy must be one of {_WEIGHT_POLICIES}"
            )
        if self.on_check_error not in _ON_CHECK_ERRORS:
            raise OperatorScoringConfigError(
                f"GraderConfig.on_check_error must be one of {_ON_CHECK_ERRORS}"
            )
        if self.flakiness_metric not in _FLAKINESS_METRICS:
            raise OperatorScoringConfigError(
                f"GraderConfig.flakiness_metric must be one of {_FLAKINESS_METRICS}"
            )


@dataclass
class LiftConfig:
    sigma_intrinsic: float = 0.10         # intrinsic per-observation noise on the L scale
    default_ceiling: float = 0.97         # expert ceiling mu* when an item omits one
    default_M: int = 20                   # baseline replay count default
    default_mu0: float = 0.55             # baseline mean default
    default_sigma0: float = 0.08          # baseline stdev default
    min_ceiling_gap: float = 1e-6         # denom below this => degenerate ceiling
    crn_enabled: bool = False             # thread baseline seeds + paired variance reduction
    crn_rho: float = 0.0                  # CRN correlation, clamped to [0, 1]
    max_se: float = 1000.0                # SE for a degenerate ceiling => Layer D info ~0
    prior_sigma0: float = 0.08            # fallback baseline stdev when M<2 or sample sigma0==0
    min_s: float = 1e-6                   # positive floor on the emitted s so Layer D always accepts it
    display_decimals: int = 4

    def __post_init__(self) -> None:
        if self.default_M < 1:
            raise OperatorScoringConfigError("LiftConfig.default_M must be >= 1")
        if self.min_s <= 0:
            raise OperatorScoringConfigError("LiftConfig.min_s must be > 0")
        if self.sigma_intrinsic < 0:
            raise OperatorScoringConfigError("LiftConfig.sigma_intrinsic must be >= 0")
        if self.default_sigma0 < 0:
            raise OperatorScoringConfigError("LiftConfig.default_sigma0 must be >= 0")
        if self.prior_sigma0 < 0:
            raise OperatorScoringConfigError("LiftConfig.prior_sigma0 must be >= 0")
        if self.default_ceiling == self.default_mu0:
            raise OperatorScoringConfigError(
                "LiftConfig.default_ceiling must differ from default_mu0"
            )
        # CRN correlation is clamped, not rejected: an out-of-range rho degrades
        # gracefully to the nearest valid paired-variance reduction.
        self.crn_rho = min(1.0, max(0.0, self.crn_rho))


@dataclass
class IrtConfig:
    tau2: float = 1.0                     # prior variance theta~N(0,tau2); MUST be >0
    init_theta: float = 0.0               # Newton start (prior mean); always among the multi-starts
    max_iter: int = 100
    tol: float = 1e-10                    # step-size convergence |t*delta|
    grad_tol: float = 1e-8                # gradient convergence |grad|
    z: float = 1.96                       # CI multiplier; MUST be >0
    max_backtrack: int = 50               # step-halving line-search cap
    hess_neg_eps: float = 1e-12           # observed Hessian must be < -eps to be used
    # The MAP log-posterior is non-concave / bimodal when items give conflicting
    # evidence, so a single Newton run from init_theta can settle in a local (or
    # even a minimum) mode. fit_ability runs Newton from n_starts points spanning
    # theta_bounds (plus init_theta) and keeps the global argmax by log-posterior.
    n_starts: int = 11
    theta_bounds: tuple[float, float] = (-6.0, 6.0)   # clamp during iteration; also the multi-start span
    dims: tuple[str, ...] = ("dec", "ver", "rec", "taste", "eff")  # MD dimension names
    md_max_iter: int = 100
    md_tol: float = 1e-10
    md_ridge: float = 1e-9                # ridge added to Fisher matrix before inversion

    def __post_init__(self) -> None:
        if self.tau2 <= 0:
            raise OperatorScoringConfigError("IrtConfig.tau2 must be > 0")
        if self.z <= 0:
            raise OperatorScoringConfigError("IrtConfig.z must be > 0")
        if self.max_iter < 1:
            raise OperatorScoringConfigError("IrtConfig.max_iter must be >= 1")
        if self.tol <= 0:
            raise OperatorScoringConfigError("IrtConfig.tol must be > 0")
        if self.n_starts < 1:
            raise OperatorScoringConfigError("IrtConfig.n_starts must be >= 1")
        if len(self.dims) < 1:
            raise OperatorScoringConfigError("IrtConfig.dims must be non-empty")


@dataclass
class PredictiveConfig:
    gamma: tuple[float, ...] = (-0.80, 1.10, 0.60, -0.15)  # default/fallback weights
    feature_names: tuple[str, ...] = ("theta", "v", "agent")  # len == len(gamma)-1
    sigma_reg: float = 0.05               # residual regression SD; sigma_reg^2 is the EIV term
    z: float = 1.96                       # prediction-interval quantile; MUST be >0
    calibration_method: str = "none"      # "none" | "platt" | "isotonic"
    ridge_lambda: float = 1e-2            # L2 on non-intercept gamma (IRLS stability)
    penalize_intercept: bool = False
    fit_intercept: bool = True
    max_iter: int = 100
    tol: float = 1e-8
    platt_smoothing: bool = True          # Platt (1999) target smoothing t+/t-
    isotonic_interp: str = "linear"       # "linear" (np.interp) | "previous"
    estimate_sigma_reg: bool = False      # else use config sigma_reg (oracle path)

    def __post_init__(self) -> None:
        if len(self.gamma) != len(self.feature_names) + 1:
            raise OperatorScoringConfigError(
                "PredictiveConfig requires len(gamma) == len(feature_names) + 1"
            )
        if self.sigma_reg < 0:
            raise OperatorScoringConfigError("PredictiveConfig.sigma_reg must be >= 0")
        if self.z <= 0:
            raise OperatorScoringConfigError("PredictiveConfig.z must be > 0")
        if self.calibration_method not in _CALIBRATION_METHODS:
            raise OperatorScoringConfigError(
                f"PredictiveConfig.calibration_method must be one of {_CALIBRATION_METHODS}"
            )


@dataclass
class PersistenceConfig:
    item_backend: str = "memory"          # "memory" | "json"
    item_path: str | None = None          # required when item_backend="json"
    calibration_backend: str = "memory"
    calibration_path: str | None = None
    autosave: bool = True

    def __post_init__(self) -> None:
        if self.item_backend not in _BACKENDS:
            raise OperatorScoringConfigError(
                f"PersistenceConfig.item_backend must be one of {_BACKENDS}"
            )
        if self.calibration_backend not in _BACKENDS:
            raise OperatorScoringConfigError(
                f"PersistenceConfig.calibration_backend must be one of {_BACKENDS}"
            )
        if self.item_backend == "json" and self.item_path is None:
            raise OperatorScoringConfigError(
                "PersistenceConfig.item_path is required when item_backend='json'"
            )
        if self.calibration_backend == "json" and self.calibration_path is None:
            raise OperatorScoringConfigError(
                "PersistenceConfig.calibration_path is required when "
                "calibration_backend='json'"
            )


@dataclass
class OperatorScoringConfig:
    profile: str = "balanced"             # named-profile selector; unknown -> balanced
    version: int = 1
    rng_seed: int = 0                     # seed for SeededRNG; the core's only entropy source
    grader: GraderConfig = field(default_factory=GraderConfig)
    lift: LiftConfig = field(default_factory=LiftConfig)
    irt: IrtConfig = field(default_factory=IrtConfig)
    predictive: PredictiveConfig = field(default_factory=PredictiveConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)


def _pick(cls: type, data: Any, **overrides: Any) -> Any:
    """Construct dataclass ``cls`` from ``data``, ignoring unknown keys.

    List values destined for a tuple-typed field are converted to tuples so JSON
    arrays round-trip. ``overrides`` win over ``data`` (used to inject an already
    built nested dataclass).
    """
    if not isinstance(data, dict):
        data = {}
    kwargs: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name in overrides:
            kwargs[f.name] = overrides[f.name]
            continue
        if f.name not in data:
            continue
        value = data[f.name]
        # Coerce JSON arrays into tuples for tuple-defaulted fields.
        if isinstance(f.default, tuple) and isinstance(value, list):
            value = tuple(value)
        kwargs[f.name] = value
    return cls(**kwargs)


def resolve_config(raw: str | dict[str, Any] | None) -> OperatorScoringConfig:
    """Resolve raw config (JSON string, dict, or ``None``) into a config tree.

    Empty/missing/malformed input yields all-default config. Unknown keys are
    ignored; any invalid value falls back to the full defaults rather than
    raising, so callers never have to guard this.
    """
    data: dict[str, Any] = {}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            parsed = {}
        if isinstance(parsed, dict):
            data = parsed
    elif isinstance(raw, dict):
        data = raw

    try:
        grader_raw = data.get("grader", {})
        if not isinstance(grader_raw, dict):
            grader_raw = {}
        mutation = _pick(MutationConfig, grader_raw.get("mutation", {}))
        grader = _pick(GraderConfig, grader_raw, mutation=mutation)
        lift = _pick(LiftConfig, data.get("lift", {}))
        irt = _pick(IrtConfig, data.get("irt", {}))
        predictive = _pick(PredictiveConfig, data.get("predictive", {}))
        persistence = _pick(PersistenceConfig, data.get("persistence", {}))
        return OperatorScoringConfig(
            profile=data.get("profile", "balanced"),
            version=data.get("version", 1),
            rng_seed=data.get("rng_seed", 0),
            grader=grader,
            lift=lift,
            irt=irt,
            predictive=predictive,
            persistence=persistence,
        )
    except Exception:
        return OperatorScoringConfig()
