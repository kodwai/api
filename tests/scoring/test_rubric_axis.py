"""Tests for the bespoke per-challenge rubric axis (Challenge Rubric).

Covers:
  1. Challenge WITH rubric + API key  → challenge_rubric axis with 3 signals, direction + lift present.
  2. Challenge WITH rubric, NO key    → challenge_rubric axis present but all signals skipped,
                                        leaderboard_eligible=0.
  3. Challenge WITHOUT rubric         → profile axes unchanged (direction/outcome/lift), no
                                        challenge_rubric axis.
  4. LLMJudge.judge_rubric unit test  → parses dimensions, clamps >10 to 10, returns {} on HTTP 500.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.database import execute, fetch_one
from app.services.scoring import score_submission
from app.services.scoring.config import resolve_config
from app.services.scoring.llm import LLMJudge, LLM_SIGNALS
from app.services.scoring.models import ScoringContext

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

RUBRIC_3_DIMS = [
    {
        "name": "Functional Correctness",
        "weight": 10,
        "description": "Does the code fulfil every stated requirement? "
                       "0=wrong, 5=partially correct, 10=fully correct per all acceptance criteria.",
    },
    {
        "name": "Code Readability",
        "weight": 5,
        "description": "Is the code clean and self-documenting? "
                       "0=unreadable, 5=adequate, 10=exemplary naming/structure.",
    },
    {
        "name": "Edge-Case Handling",
        "weight": 3,
        "description": "Does the solution handle nulls/empty/boundary inputs correctly? "
                       "0=none handled, 5=most handled, 10=all handled.",
    },
]

GOOD_TURNS = [
    {"role": "user", "content": "Build X. Must handle empty input and reject negatives."},
    {"role": "assistant", "content": "ok"},
    {"role": "user", "content": "No, that's wrong — you skipped the empty-input case. Fix it."},
    {"role": "assistant", "content": "fixed"},
    {"role": "user", "content": "Great, now add a test for the negative case."},
    {"role": "assistant", "content": "done"},
]


def _judgment_for_llm_signals(score: float = 7.0) -> dict:
    """Return a mocked judge() result for standard LLM_SIGNALS."""
    return {k: {"score": score, "reason": "r", "evidence": ["e"]} for k in LLM_SIGNALS}


def _rubric_judgment(scores: dict[str, float]) -> dict:
    """Build a mocked judge_rubric() result keyed by dimension name."""
    return {
        name: {"score": s, "justification": f"justification for {name}", "evidence": [f"evidence for {name}"]}
        for name, s in scores.items()
    }


def _seed(scoring_config: str | dict, *, with_key: bool, test_results=None):
    """Seed minimal DB rows for a single scoring run."""
    sc = json.dumps(scoring_config) if isinstance(scoring_config, dict) else scoring_config
    execute(
        "INSERT INTO users (id, email, password_hash, name, user_type, email_verified) "
        "VALUES ('u1','d@d.com','x','Dev','developer',1)"
    )
    execute(
        "INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, "
        "difficulty, category, time_limit_minutes, scoring_config) "
        "VALUES ('c1','u1','T','t','d','Build X','easy','algo',60,?)",
        (sc,),
    )
    execute("INSERT INTO developer_profiles (user_id) VALUES ('u1')")
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id, status, agent_trace, "
        "code_snapshot, test_results, time_taken_ms) "
        "VALUES ('s1','c1','u1','scoring',?,?,?,?)",
        (
            json.dumps({"turns": GOOD_TURNS}),
            json.dumps([{"path": "a.py", "content": "def f():\n    return 1\n"}]),
            json.dumps(test_results) if test_results is not None else None,
            600000,
        ),
    )
    if with_key:
        execute(
            "INSERT INTO api_keys (id, user_id, encrypted_key, key_iv, key_last4, is_active, label) "
            "VALUES ('k1','u1','enc','iv','test',1,'L')"
        )


# ---------------------------------------------------------------------------
# 1. With rubric + API key → challenge_rubric axis properly scored
# ---------------------------------------------------------------------------

def test_rubric_axis_with_key_has_three_signals_and_correct_score():
    """A challenge with a 3-dim rubric and an API key must produce:
    - axes: direction (45 pts), challenge_rubric (45 pts), lift (10 pts)
    - challenge_rubric.signals == 3 entries (one per dim), none skipped
    - score reflects mocked dim scores
    - leaderboard_eligible == 1
    """
    scoring_cfg = {"profile": "spec_heavy", "rubric": RUBRIC_3_DIMS}

    mocked_rubric_scores = {
        "Functional Correctness": 8.0,
        "Code Readability": 6.0,
        "Edge-Case Handling": 4.0,
    }
    # Weighted average: (8*10 + 6*5 + 4*3) / (10+5+3) = (80+30+12)/18 = 122/18 ≈ 6.7778
    # × 45 ≈ 30.5
    expected_rubric_score = round(45.0 * (8.0 * 10 + 6.0 * 5 + 4.0 * 3) / (10.0 * (10 + 5 + 3)), 2)
    # Actually: (score/10 * weight), total_weight = 18
    # weighted_sum = (8/10)*10 + (6/10)*5 + (4/10)*3 = 8 + 3 + 1.2 = 12.2
    # rubric_score = 45 * (12.2 / 18) = 45 * 0.6778 ≈ 30.5
    expected_rubric_score = round(45.0 * ((8.0 / 10.0 * 10 + 6.0 / 10.0 * 5 + 4.0 / 10.0 * 3) / 18.0), 2)

    _seed(scoring_cfg, with_key=True, test_results={"passed": 5, "total": 10})

    with patch("app.services.scoring.engine.decrypt_api_key", return_value="sk-test"), \
         patch("app.services.scoring.llm.LLMJudge.judge",
               return_value=_judgment_for_llm_signals(7.0)), \
         patch("app.services.scoring.llm.LLMJudge.judge_rubric",
               return_value=_rubric_judgment(mocked_rubric_scores)):
        score_submission("s1")

    row = fetch_one(
        "SELECT score, leaderboard_eligible, score_breakdown FROM submissions WHERE id='s1'"
    )
    assert row is not None
    bd = json.loads(row["score_breakdown"])

    axis_names = [a["name"] for a in bd["axes"]]
    assert "direction" in axis_names
    assert "challenge_rubric" in axis_names
    assert "lift" in axis_names
    assert "outcome" not in axis_names, "outcome axis must not appear when rubric is present"

    # Find each axis
    dir_axis = next(a for a in bd["axes"] if a["name"] == "direction")
    rubric_axis = next(a for a in bd["axes"] if a["name"] == "challenge_rubric")
    lift_axis = next(a for a in bd["axes"] if a["name"] == "lift")

    # Points
    assert dir_axis["points"] == 45.0
    assert rubric_axis["points"] == 45.0
    assert lift_axis["points"] == 10.0

    # challenge_rubric: 3 signals, none skipped
    assert len(rubric_axis["signals"]) == 3
    assert all(not s["skipped"] for s in rubric_axis["signals"])

    # Score matches expected weighted average
    assert abs(rubric_axis["score"] - expected_rubric_score) < 0.01

    # leaderboard_eligible
    assert row["leaderboard_eligible"] == 1


# ---------------------------------------------------------------------------
# 2. With rubric, NO key → challenge_rubric skipped, ineligible
# ---------------------------------------------------------------------------

def test_rubric_axis_no_key_is_skipped_and_ineligible():
    """Without an API key, the challenge_rubric axis must be present but entirely skipped,
    and leaderboard_eligible must be 0.
    """
    scoring_cfg = {"profile": "spec_heavy", "rubric": RUBRIC_3_DIMS}
    _seed(scoring_cfg, with_key=False, test_results={"passed": 5, "total": 10})
    score_submission("s1")

    row = fetch_one(
        "SELECT score, leaderboard_eligible, score_breakdown FROM submissions WHERE id='s1'"
    )
    assert row is not None
    bd = json.loads(row["score_breakdown"])

    axis_names = [a["name"] for a in bd["axes"]]
    assert "challenge_rubric" in axis_names

    rubric_axis = next(a for a in bd["axes"] if a["name"] == "challenge_rubric")
    # All 3 signals must be present and skipped
    assert len(rubric_axis["signals"]) == 3
    assert all(s["skipped"] for s in rubric_axis["signals"])

    # Score must be 0 (no LLM judgment)
    assert rubric_axis["score"] == 0.0

    # leaderboard_eligible == 0
    assert row["leaderboard_eligible"] == 0

    # overall score is still produced (direction + lift contribute)
    assert row["score"] is not None


# ---------------------------------------------------------------------------
# 3. No rubric → profile axes unchanged
# ---------------------------------------------------------------------------

def test_no_rubric_uses_profile_axes():
    """A challenge WITHOUT a rubric must use the standard profile axes
    (direction/outcome/lift) and must NOT have a challenge_rubric axis.
    """
    # Empty scoring_config → balanced profile
    _seed("{}", with_key=True, test_results={"passed": 10, "total": 10})

    with patch("app.services.scoring.engine.decrypt_api_key", return_value="sk-test"), \
         patch("app.services.scoring.llm.LLMJudge.judge",
               return_value=_judgment_for_llm_signals(7.0)):
        score_submission("s1")

    row = fetch_one("SELECT score_breakdown FROM submissions WHERE id='s1'")
    bd = json.loads(row["score_breakdown"])

    axis_names = [a["name"] for a in bd["axes"]]
    assert "challenge_rubric" not in axis_names
    assert "direction" in axis_names
    assert "outcome" in axis_names
    assert "lift" in axis_names


# ---------------------------------------------------------------------------
# 4. judge_rubric unit tests (mock httpx)
# ---------------------------------------------------------------------------

def _ctx_for_rubric(turns=None) -> ScoringContext:
    return ScoringContext(
        submission={},
        challenge={"problem_statement_md": "Build a sorter."},
        config=resolve_config({"profile": "spec_heavy", "rubric": RUBRIC_3_DIMS}),
        test_results=None,
        code_snapshot=[{"path": "sol.py", "content": "def sort(x): return sorted(x)"}],
        git_log=[],
        agent_trace={"turns": turns if turns is not None else GOOD_TURNS},
    )


def _fake_response_rubric(dimensions: list[dict]) -> MagicMock:
    """Build a mock httpx response returning rubric JSON."""
    body = {"content": [{"type": "text", "text": json.dumps({"dimensions": dimensions})}]}
    m = MagicMock(status_code=200)
    m.json.return_value = body
    return m


def test_judge_rubric_parses_dimensions():
    """judge_rubric must parse dimension names/scores and return correct dict."""
    dims = [
        {"name": "Functional Correctness", "score": 8.0,
         "justification": "All cases pass", "evidence": ["passes all tests"]},
        {"name": "Code Readability", "score": 6.0,
         "justification": "Reasonable naming"},
        {"name": "Edge-Case Handling", "score": 5.0,
         "justification": "Most edges covered"},
    ]
    ctx = _ctx_for_rubric()
    with patch("app.services.scoring.llm.httpx.post", return_value=_fake_response_rubric(dims)):
        out = LLMJudge("sk-test").judge_rubric(ctx, RUBRIC_3_DIMS)

    assert "Functional Correctness" in out
    assert out["Functional Correctness"]["score"] == 8.0
    assert out["Functional Correctness"]["justification"] == "All cases pass"
    assert out["Code Readability"]["score"] == 6.0
    assert out["Edge-Case Handling"]["score"] == 5.0


def test_judge_rubric_clamps_score_above_10():
    """Scores above 10 must be clamped to 10."""
    dims = [
        {"name": "Functional Correctness", "score": 15.0,
         "justification": "Way too high"},
        {"name": "Code Readability", "score": 11.0,
         "justification": "Also too high"},
        {"name": "Edge-Case Handling", "score": 10.0,
         "justification": "Exactly at ceiling"},
    ]
    ctx = _ctx_for_rubric()
    with patch("app.services.scoring.llm.httpx.post", return_value=_fake_response_rubric(dims)):
        out = LLMJudge("sk-test").judge_rubric(ctx, RUBRIC_3_DIMS)

    assert out["Functional Correctness"]["score"] == 10.0
    assert out["Code Readability"]["score"] == 10.0
    assert out["Edge-Case Handling"]["score"] == 10.0


def test_judge_rubric_returns_empty_on_http_500():
    """judge_rubric must return {} on HTTP error, never raise."""
    err = MagicMock(status_code=500, text="internal server error")
    ctx = _ctx_for_rubric()
    with patch("app.services.scoring.llm.httpx.post", return_value=err):
        out = LLMJudge("sk-test").judge_rubric(ctx, RUBRIC_3_DIMS)
    assert out == {}
