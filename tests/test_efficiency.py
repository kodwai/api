from app.services.scoring.engine import efficiency_outcome, _trace_turns, _trace_tokens


def test_turns_from_trace():
    assert _trace_turns({"turns": [1, 2, 3]}) == 3
    assert _trace_turns({}) is None
    assert _trace_turns(None) is None


def test_tokens_from_trace():
    assert _trace_tokens({"token_usage": {"input": 100, "output": 50}}) == 150
    assert _trace_tokens({"turns": []}) is None


def test_efficiency_outcome_rewards_fewer_turns():
    few = efficiency_outcome(90, "medium", 6)
    many = efficiency_outcome(90, "medium", 24)
    assert few > many
    assert efficiency_outcome(90, "medium", None) == 90      # no turns -> raw score
    assert 0 <= efficiency_outcome(90, "medium", 6) <= 100
