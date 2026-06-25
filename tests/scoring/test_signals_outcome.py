from app.services.scoring.models import ScoringContext
from app.services.scoring.signals import outcome


def _ctx(**kw):
    base = dict(submission={}, challenge={}, config=None, test_results=None,
                code_snapshot=[], git_log=[], agent_trace=None)
    base.update(kw)
    return ScoringContext(**base)


def test_tests_all_pass():
    r = outcome.tests(_ctx(test_results={"passed": 10, "total": 10}))
    assert r.value == 1.0


def test_tests_none_submitted_is_zero():
    assert outcome.tests(_ctx(test_results=None)).value == 0.0


def test_code_quality_clean_high():
    snap = [{"path": "a.py", "content": "def add(a, b):\n    return a + b\n"}]
    assert outcome.code_quality(_ctx(code_snapshot=snap)).value >= 0.9


def test_code_quality_dirty_low():
    dirty = "def f():\n" + "    print('x')  # TODO fix\n" * 20
    snap = [{"path": "a.py", "content": dirty}]
    assert outcome.code_quality(_ctx(code_snapshot=snap)).value < 0.5


def test_complexity_deep_nesting_penalized():
    deep = "{" * 10 + "x" + "}" * 10
    snap = [{"path": "a.ts", "content": deep}]
    assert outcome.complexity(_ctx(code_snapshot=snap)).value < 1.0
