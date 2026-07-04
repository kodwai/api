"""DB-backed wiring tests for the operator scoring live path (SCORING_DESIGN section 11).

These inherit the real ``tests/conftest.py`` autouse DB fixture (fresh in-memory
libSQL with all migrations applied), so migration ``037`` and the engine edits are
exercised end-to-end. Non-breakage is the load-bearing property: with no
``operator_item_params`` row the engine's headline ``overall`` and legacy badge
are unchanged; adding a row only swaps the badge source, never the score.
"""
import json
import math

from app.core.database import execute, fetch_all, fetch_one
from app.services.operator_scoring_adapter import (
    operator_baseline_lift,
    recompute_user_ability,
)
from app.services.scoring import score_submission


# ── seed helpers ──────────────────────────────────────────────────────────────

def _seed_user(user_id: str = "u1") -> None:
    execute(
        "INSERT INTO users (id, email, password_hash, name, user_type, email_verified) "
        "VALUES (?, ?, 'x', 'Dev', 'developer', 1)",
        (user_id, f"{user_id}@d.com"),
    )
    execute("INSERT INTO developer_profiles (user_id) VALUES (?)", (user_id,))


def _seed_challenge(challenge_id: str = "c1", ai_baseline=None, created_by: str = "u1") -> None:
    execute(
        "INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, "
        "difficulty, category, time_limit_minutes, scoring_config, ai_baseline) "
        "VALUES (?, ?, 'T', ?, 'd', 'Build X', 'easy', 'algo', 60, '{}', ?)",
        (challenge_id, created_by, challenge_id, ai_baseline),
    )


def _seed_submission(
    submission_id: str = "s1",
    challenge_id: str = "c1",
    user_id: str = "u1",
    *,
    status: str = "scoring",
    score=None,
    operator_l=None,
    operator_s=None,
    test_results=None,
) -> None:
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id, status, score, agent_trace, "
        "code_snapshot, test_results, time_taken_ms, operator_l, operator_s) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            submission_id, challenge_id, user_id, status, score,
            json.dumps({"turns": [{"role": "user", "content": "Build X."}]}),
            json.dumps([{"path": "a.py", "content": "def f():\n    return 1\n"}]),
            json.dumps(test_results) if test_results else None,
            600000, operator_l, operator_s,
        ),
    )


def _seed_operator_item(
    challenge_id: str = "c1",
    *,
    a: float = 1.8,
    b: float = 0.8,
    s: float = 0.11,
    mu_baseline: float = 0.55,
    sigma_baseline: float = 0.08,
    baseline_m: int = 20,
    ceiling: float = 0.97,
    sigma_intrinsic: float = 0.10,
) -> None:
    execute(
        "INSERT INTO operator_item_params "
        "(challenge_id, a, b, s, mu_baseline, sigma_baseline, baseline_m, ceiling, sigma_intrinsic) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (challenge_id, a, b, s, mu_baseline, sigma_baseline, baseline_m, ceiling, sigma_intrinsic),
    )


# ── migration 037 columns/tables exist ───────────────────────────────────────

def test_migration_037_tables_and_columns_exist():
    tables = {r["name"] for r in fetch_all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "operator_item_params" in tables
    assert "operator_calibration" in tables

    dp_cols = {r["name"] for r in fetch_all("PRAGMA table_info(developer_profiles)")}
    assert {"ability_theta", "ability_se", "ability_updated_at"} <= dp_cols

    sub_cols = {r["name"] for r in fetch_all("PRAGMA table_info(submissions)")}
    assert {"operator_l", "operator_s"} <= sub_cols

    item_cols = {r["name"] for r in fetch_all("PRAGMA table_info(operator_item_params)")}
    assert {
        "challenge_id", "a", "b", "s", "mu_baseline", "sigma_baseline",
        "baseline_m", "ceiling", "sigma_intrinsic", "discrimination_vec",
    } <= item_cols


# ── operator_baseline_lift: None without a row, badge with one ────────────────

def test_operator_baseline_lift_none_without_row():
    _seed_user()
    _seed_challenge("c1")
    assert operator_baseline_lift("c1", 0.845, None) is None


def test_operator_baseline_lift_badge_with_row():
    _seed_user()
    _seed_challenge("c1")
    _seed_operator_item("c1")

    badge = operator_baseline_lift("c1", 0.845, None)
    assert badge is not None

    d = badge.to_badge_dict()
    assert d["source"] == "operator"
    assert "beat" in d and "delta" in d
    assert "L" in d and "s" in d
    # outcome 0.845 clears the 0.55 baseline mean -> beat, positive delta.
    assert d["beat"] is True
    assert d["delta"] > 0.0
    # Full-precision L/s reproduce the Layer-E acceptance oracle (tol 1e-3).
    assert math.isclose(badge.L, 0.7023809523809523, abs_tol=1e-3)
    assert math.isclose(badge.s, 0.10869249724298408, abs_tol=1e-3)


# ── recompute_user_ability: None below one item, finite with one ──────────────

def test_recompute_ability_none_below_one_item():
    _seed_user()
    _seed_challenge("c1")
    _seed_operator_item("c1")
    # A scored submission that carries NO operator_l -> not counted -> None.
    _seed_submission("s1", status="scored", score=80.0, operator_l=None)
    assert recompute_user_ability("u1") is None


def test_recompute_ability_finite_with_one_item():
    _seed_user()
    _seed_challenge("c1")
    _seed_operator_item("c1", a=1.8, b=0.8)
    _seed_submission(
        "s1", status="scored", score=80.0,
        operator_l=0.7023809523809523, operator_s=0.10869249724298408,
    )
    ability = recompute_user_ability("u1")
    assert ability is not None
    assert ability.n_items == 1
    assert math.isfinite(ability.theta_hat)
    assert math.isfinite(ability.se)
    assert ability.se > 0.0


# ── engine: overall unchanged with vs without an operator row ─────────────────

def test_engine_overall_unchanged_with_operator_row():
    _seed_user()
    _seed_challenge("c1", ai_baseline=60.0)
    _seed_submission("s1", test_results={"passed": 8, "total": 10})

    # Run 1: no operator_item_params row -> legacy static badge, headline score.
    score_submission("s1")
    without = fetch_one("SELECT score, score_breakdown, operator_l FROM submissions WHERE id='s1'")
    overall_without = without["score"]
    bd_without = json.loads(without["score_breakdown"])
    assert without["operator_l"] is None
    # Legacy badge keeps beat/delta and carries no operator source.
    assert bd_without["baseline_lift"] is not None
    assert "beat" in bd_without["baseline_lift"]
    assert "delta" in bd_without["baseline_lift"]
    assert bd_without["baseline_lift"].get("source") is None

    # Run 2: add a calibrated item row, reset the submission, re-score.
    _seed_operator_item("c1")
    execute(
        "UPDATE submissions SET status='scoring', score=NULL, score_breakdown=NULL, "
        "operator_l=NULL, operator_s=NULL, scored_at=NULL WHERE id='s1'"
    )
    score_submission("s1")
    with_row = fetch_one("SELECT score, score_breakdown, operator_l, operator_s FROM submissions WHERE id='s1'")
    bd_with = json.loads(with_row["score_breakdown"])

    # Headline score is bit-identical; only the badge source changed.
    assert with_row["score"] == overall_without
    assert bd_with["overall"] == bd_without["overall"]
    assert bd_with["baseline_lift"]["source"] == "operator"
    assert "L" in bd_with["baseline_lift"] and "s" in bd_with["baseline_lift"]
    assert "beat" in bd_with["baseline_lift"] and "delta" in bd_with["baseline_lift"]
    # Full-precision L/s were persisted to the submission (NOT emitted by to_json()).
    assert with_row["operator_l"] is not None
    assert with_row["operator_s"] is not None
    assert "operator_l" not in bd_with


# ── engine: legacy baseline_lift badge keeps beat/delta ───────────────────────

def test_legacy_baseline_lift_keeps_beat_delta():
    _seed_user()
    _seed_challenge("c1", ai_baseline=40.0)
    _seed_submission("s1", test_results={"passed": 10, "total": 10})
    score_submission("s1")

    bd = json.loads(fetch_one("SELECT score_breakdown FROM submissions WHERE id='s1'")["score_breakdown"])
    badge = bd["baseline_lift"]
    assert badge is not None
    assert "beat" in badge
    assert "delta" in badge
    assert badge.get("source") is None
