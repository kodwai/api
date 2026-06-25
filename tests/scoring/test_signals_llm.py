from app.services.scoring.models import ScoringContext
from app.services.scoring.signals import direction, lift


def _ctx(judgment):
    return ScoringContext(submission={}, challenge={}, config=None, test_results=None,
                          code_snapshot=[], git_log=[], agent_trace=None, judgment=judgment)


def test_adapter_normalizes_to_0_1():
    r = direction.spec_precision(_ctx({"spec_precision": {"score": 8, "reason": "ok", "evidence": []}}))
    assert r.value == 0.8 and r.skipped is False


def test_adapter_skipped_without_judgment():
    r = direction.intent_fidelity(_ctx(None))
    assert r.skipped is True and r.value == 0.0


def test_trap_coverage_skipped_without_judgment():
    assert lift.trap_coverage(_ctx(None)).skipped is True
