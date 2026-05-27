from app.services.scoring.models import ScoringContext
from app.services.scoring.signals import direction


def _ctx(turns):
    return ScoringContext(submission={}, challenge={}, config=None, test_results=None,
                          code_snapshot=[], git_log=[], agent_trace={"turns": turns})


GOOD_DRIVER = [
    {"role": "user", "content": "Build a rate limiter. Must reject >100 req/min per IP, return 429."},
    {"role": "assistant", "content": "Here is a sliding-window limiter..."},
    {"role": "user", "content": "This is wrong — you used a fixed window. Use a sliding window instead."},
    {"role": "assistant", "content": "Fixed. Now sliding window..."},
    {"role": "user", "content": "Good. Now add a unit test for the boundary at exactly 100 requests."},
]
ONE_SHOT = [
    {"role": "user", "content": "Build a rate limiter that rejects more than 100 requests per minute."},
    {"role": "assistant", "content": "Done, here is the full solution..."},
]


def test_one_shot_penalty_low_for_one_shot():
    assert direction.one_shot_penalty(_ctx(ONE_SHOT)).value <= 0.34


def test_one_shot_penalty_high_for_engaged():
    assert direction.one_shot_penalty(_ctx(GOOD_DRIVER)).value >= 0.66


def test_recovery_detects_correction():
    assert direction.recovery(_ctx(GOOD_DRIVER)).value >= 0.5


def test_recovery_neutral_without_corrections():
    assert direction.recovery(_ctx(ONE_SHOT)).value == 0.7


def test_recovery_single_correction_monotonic_vs_neutral():
    """One correction must score >= neutral baseline (0.7); was 0.5 before fix."""
    single_correction = [
        {"role": "user", "content": "Build a rate limiter."},
        {"role": "assistant", "content": "Here is a fixed-window implementation..."},
        {"role": "user", "content": "Wrong — you should use a sliding window instead."},
    ]
    result = direction.recovery(_ctx(single_correction))
    assert result.value >= 0.7, f"single correction scored {result.value} < 0.7 (non-monotonic)"
