from app.services.scoring.config import resolve_config
from app.services.scoring.models import ScoringContext
from app.services.scoring.signals import direction, lift


def _ctx(judgment, traps=({"id": "t", "description": "d"},)):
    return ScoringContext(submission={}, challenge={}, config=resolve_config({"traps": list(traps)}), test_results=None,
                          code_snapshot=[], git_log=[], agent_trace=None, judgment=judgment)


def test_adapter_normalizes_to_0_1():
    r = direction.spec_precision(_ctx({"spec_precision": {"score": 8, "reason": "ok", "evidence": []}}))
    assert r.value == 0.8 and r.skipped is False


def test_adapter_skipped_without_judgment():
    r = direction.intent_fidelity(_ctx(None))
    assert r.skipped is True and r.value == 0.0


def test_trap_coverage_skipped_without_judgment():
    assert lift.trap_coverage(_ctx(None)).skipped is True


def test_trap_coverage_skipped_when_challenge_has_no_traps():
    # Even with a judgment present, a trapless challenge must not surface the judge's placeholder 5.
    r = lift.trap_coverage(_ctx({"trap_coverage": {"score": 5, "reason": "none listed"}}, traps=()))
    assert r.skipped is True
