import json
from unittest.mock import patch, MagicMock

from app.services.scoring.llm import LLMJudge, LLM_SIGNALS
from app.services.scoring.models import ScoringContext
from app.services.scoring.config import resolve_config


def _ctx():
    return ScoringContext(submission={}, challenge={"problem_statement_md": "x"},
                          config=resolve_config("{}"), test_results=None,
                          code_snapshot=[], git_log=[], agent_trace={"turns": []})


def _fake_response(scores: dict):
    body = {"content": [{"type": "text", "text": json.dumps(scores)}]}
    m = MagicMock(status_code=200)
    m.json.return_value = body
    return m


def test_judge_parses_and_clamps():
    payload = {k: {"score": 12, "reason": "r", "evidence": ["e"]} for k in LLM_SIGNALS}
    with patch("app.services.scoring.llm.httpx.post", return_value=_fake_response(payload)):
        out = LLMJudge("sk-test").judge(_ctx())
    assert out["spec_precision"]["score"] == 10.0  # clamped from 12
    assert out["intent_fidelity"]["reason"] == "r"


def test_judge_returns_empty_on_http_error():
    err = MagicMock(status_code=500, text="boom")
    with patch("app.services.scoring.llm.httpx.post", return_value=err):
        assert LLMJudge("sk-test").judge(_ctx()) == {}


def test_judge_median_of_samples():
    seq = [_fake_response({k: {"score": s} for k in LLM_SIGNALS}) for s in (4, 8, 6)]
    with patch("app.services.scoring.llm.httpx.post", side_effect=seq):
        out = LLMJudge("sk-test", samples=3).judge(_ctx())
    assert out["spec_precision"]["score"] == 6.0  # median(4,8,6)
