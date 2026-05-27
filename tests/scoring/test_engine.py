import json
from unittest.mock import patch

from app.core.database import execute, fetch_one
from app.services.scoring import score_submission
from app.services.scoring.llm import LLM_SIGNALS


def _seed(trace, *, with_key: bool, test_results=None):
    execute("INSERT INTO users (id, email, password_hash, name, user_type, email_verified) "
            "VALUES ('u1','d@d.com','x','Dev','developer',1)")
    execute("INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, "
            "difficulty, category, time_limit_minutes, scoring_config) "
            "VALUES ('c1','u1','T','t','d','Build X','easy','algo',60,'{}')")
    execute("INSERT INTO developer_profiles (user_id) VALUES ('u1')")
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id, status, agent_trace, code_snapshot, test_results, time_taken_ms) "
        "VALUES ('s1','c1','u1','scoring',?,?,?,?)",
        (json.dumps({"turns": trace}),
         json.dumps([{"path": "a.py", "content": "def f():\n    return 1\n"}]),
         json.dumps(test_results) if test_results else None,
         600000),
    )
    if with_key:
        # is_active key so the engine attaches an LLM judge (which we mock).
        execute("INSERT INTO api_keys (id, user_id, encrypted_key, key_iv, key_last4, is_active, label) "
                "VALUES ('k1','u1','enc','iv','test',1,'L')")


GOOD = [
    {"role": "user", "content": "Build X. Must handle empty input and reject negatives."},
    {"role": "assistant", "content": "ok"},
    {"role": "user", "content": "No, that's wrong — you skipped the empty-input case. Fix it."},
    {"role": "assistant", "content": "fixed"},
    {"role": "user", "content": "Great, now add a test for the negative case at the boundary."},
]
ONE_SHOT = [{"role": "user", "content": "Build X."}, {"role": "assistant", "content": "done"}]


def _judgment(score):
    return {k: {"score": score, "reason": "r", "evidence": ["e"]} for k in LLM_SIGNALS}


def test_one_shot_scores_lower_than_good_driver():
    # Both get the SAME LLM judgment; the difference must come from the heuristic
    # direction signals (recovery, one_shot_penalty), proving process is what moves the score.
    with patch("app.services.scoring.engine.decrypt_api_key", return_value="sk-test"), \
         patch("app.services.scoring.llm.LLMJudge.judge", return_value=_judgment(6)):
        _seed(GOOD, with_key=True, test_results={"passed": 10, "total": 10})
        score_submission("s1")
        good = fetch_one("SELECT score FROM submissions WHERE id='s1'")["score"]

    # reset + reseed one-shot
    execute("DELETE FROM submissions"); execute("DELETE FROM challenges")
    execute("DELETE FROM api_keys"); execute("DELETE FROM developer_profiles")
    execute("DELETE FROM users")
    with patch("app.services.scoring.engine.decrypt_api_key", return_value="sk-test"), \
         patch("app.services.scoring.llm.LLMJudge.judge", return_value=_judgment(6)):
        _seed(ONE_SHOT, with_key=True, test_results={"passed": 10, "total": 10})
        score_submission("s1")
        oneshot = fetch_one("SELECT score FROM submissions WHERE id='s1'")["score"]

    assert good > oneshot


def test_no_api_key_is_leaderboard_ineligible():
    _seed(GOOD, with_key=False, test_results={"passed": 10, "total": 10})
    score_submission("s1")
    row = fetch_one("SELECT score, leaderboard_eligible, scoring_version, score_breakdown FROM submissions WHERE id='s1'")
    assert row["leaderboard_eligible"] == 0
    assert row["scoring_version"] == 2
    # still produces a score from deterministic + heuristic signals
    assert row["score"] is not None
    bd = json.loads(row["score_breakdown"])
    # LLM signals are marked skipped in the breakdown
    direction = next(a for a in bd["axes"] if a["name"] == "direction")
    assert any(s["skipped"] for s in direction["signals"])


def test_with_key_is_eligible_and_versioned():
    with patch("app.services.scoring.engine.decrypt_api_key", return_value="sk-test"), \
         patch("app.services.scoring.llm.LLMJudge.judge", return_value=_judgment(7)):
        _seed(GOOD, with_key=True, test_results={"passed": 8, "total": 10})
        score_submission("s1")
    row = fetch_one("SELECT leaderboard_eligible, scoring_version FROM submissions WHERE id='s1'")
    assert row["leaderboard_eligible"] == 1
    assert row["scoring_version"] == 2


# ── CHANGE 2: trace-quality confidence ──────────────────────────────────────

def _seed_with_trace(trace, trace_quality=None, *, with_key: bool, test_results=None):
    """Seed a submission with agent_trace that includes an explicit trace_quality field."""
    agent_trace = {"turns": trace}
    if trace_quality is not None:
        agent_trace["trace_quality"] = trace_quality
    execute("INSERT INTO users (id, email, password_hash, name, user_type, email_verified) "
            "VALUES ('u1','d@d.com','x','Dev','developer',1)")
    execute("INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, "
            "difficulty, category, time_limit_minutes, scoring_config) "
            "VALUES ('c1','u1','T','t','d','Build X','easy','algo',60,'{}')")
    execute("INSERT INTO developer_profiles (user_id) VALUES ('u1')")
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id, status, agent_trace, code_snapshot, test_results, time_taken_ms) "
        "VALUES ('s1','c1','u1','scoring',?,?,?,?)",
        (json.dumps(agent_trace),
         json.dumps([{"path": "a.py", "content": "def f():\n    return 1\n"}]),
         json.dumps(test_results) if test_results else None,
         600000),
    )
    if with_key:
        execute("INSERT INTO api_keys (id, user_id, encrypted_key, key_iv, key_last4, is_active, label) "
                "VALUES ('k1','u1','enc','iv','test',1,'L')")


FULL_TRACE = [
    {"role": "user", "content": "Build X. Must handle empty input."},
    {"role": "assistant", "content": "ok"},
    {"role": "user", "content": "No, that's wrong. Fix it."},
    {"role": "assistant", "content": "fixed"},
    {"role": "user", "content": "Now add a test for negatives."},
    {"role": "assistant", "content": "done"},
    {"role": "user", "content": "One more edge case: overflow."},
    {"role": "assistant", "content": "handled"},
    {"role": "user", "content": "Looks good, ship it."},
    {"role": "assistant", "content": "shipped"},
    {"role": "user", "content": "Final check: perf?"},
    {"role": "assistant", "content": "O(n log n)"},
]


def test_full_trace_quality_sets_confidence_high():
    """A 6-turn trace with trace_quality='full' must produce confidence='high' and trace_quality='full' in breakdown."""
    with patch("app.services.scoring.engine.decrypt_api_key", return_value="sk-test"), \
         patch("app.services.scoring.llm.LLMJudge.judge", return_value=_judgment(7)):
        _seed_with_trace(FULL_TRACE, trace_quality="full", with_key=True,
                         test_results={"passed": 10, "total": 10})
        score_submission("s1")
    row = fetch_one("SELECT score_breakdown FROM submissions WHERE id='s1'")
    bd = json.loads(row["score_breakdown"])
    assert bd["confidence"] == "high"
    assert bd["trace_quality"] == "full"


def test_none_trace_sets_confidence_none():
    """A submission with agent_trace=None must produce confidence='none' in breakdown."""
    execute("INSERT INTO users (id, email, password_hash, name, user_type, email_verified) "
            "VALUES ('u1','d@d.com','x','Dev','developer',1)")
    execute("INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, "
            "difficulty, category, time_limit_minutes, scoring_config) "
            "VALUES ('c1','u1','T','t','d','Build X','easy','algo',60,'{}')")
    execute("INSERT INTO developer_profiles (user_id) VALUES ('u1')")
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id, status, agent_trace, code_snapshot, test_results, time_taken_ms) "
        "VALUES ('s1','c1','u1','scoring',NULL,?,?,?)",
        (json.dumps([{"path": "a.py", "content": "def f(): return 1"}]),
         json.dumps({"passed": 5, "total": 10}),
         600000),
    )
    score_submission("s1")
    row = fetch_one("SELECT score_breakdown FROM submissions WHERE id='s1'")
    bd = json.loads(row["score_breakdown"])
    assert bd["confidence"] == "none"


def test_confidence_does_not_change_overall_score():
    """Two identical submissions differing only in trace_quality must produce the same overall score."""
    # Submission with trace_quality="full"
    with patch("app.services.scoring.engine.decrypt_api_key", return_value="sk-test"), \
         patch("app.services.scoring.llm.LLMJudge.judge", return_value=_judgment(7)):
        _seed_with_trace(FULL_TRACE, trace_quality="full", with_key=True,
                         test_results={"passed": 10, "total": 10})
        score_submission("s1")
    row_full = fetch_one("SELECT score, score_breakdown FROM submissions WHERE id='s1'")
    bd_full = json.loads(row_full["score_breakdown"])

    # Reset and reseed with trace_quality="partial" (same turns, same judgment)
    execute("DELETE FROM submissions"); execute("DELETE FROM challenges")
    execute("DELETE FROM api_keys"); execute("DELETE FROM developer_profiles")
    execute("DELETE FROM users")

    with patch("app.services.scoring.engine.decrypt_api_key", return_value="sk-test"), \
         patch("app.services.scoring.llm.LLMJudge.judge", return_value=_judgment(7)):
        _seed_with_trace(FULL_TRACE, trace_quality="partial", with_key=True,
                         test_results={"passed": 10, "total": 10})
        score_submission("s1")
    row_partial = fetch_one("SELECT score, score_breakdown FROM submissions WHERE id='s1'")
    bd_partial = json.loads(row_partial["score_breakdown"])

    # Scores must be identical; confidence must differ
    assert row_full["score"] == row_partial["score"]
    assert bd_full["overall"] == bd_partial["overall"]
    assert bd_full["confidence"] == "high"
    assert bd_partial["confidence"] == "low"
