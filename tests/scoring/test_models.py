from app.services.scoring.models import SignalResult, AxisResult, ScoreBreakdown, ScoringContext


def test_signal_result_defaults():
    r = SignalResult(value=0.5)
    assert r.evidence == [] and r.skipped is False


def test_breakdown_to_json_shape():
    bd = ScoreBreakdown(
        scoring_version=2,
        overall=78.4,
        axes=[AxisResult("direction", 50, 41.0, [{"name": "spec_precision", "value": 0.8}])],
        leaderboard_eligible=True,
    )
    j = bd.to_json()
    assert j["overall"] == 78.4
    assert j["axes"][0]["name"] == "direction"
    assert j["axes"][0]["signals"][0]["name"] == "spec_precision"


def test_context_turns_handles_missing_trace():
    ctx = ScoringContext(
        submission={}, challenge={}, config=None,
        test_results=None, code_snapshot=[], git_log=[], agent_trace=None,
    )
    assert ctx.turns == []
