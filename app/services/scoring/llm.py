from __future__ import annotations

import json
import logging
import statistics

import httpx

from app.core.config import settings
from app.services.scoring.models import ScoringContext

logger = logging.getLogger(__name__)

# Signals scored by the LLM, with anchored definitions sent in the prompt.
LLM_SIGNALS = {
    "spec_precision": "Did the human state clear requirements/constraints/acceptance criteria BEFORE code, vs vague 'make it work'? 0=no spec, 5=partial, 10=precise upfront contract.",
    "verification_rigor": "Did the human verify the AI's output — catch mistakes, push back, re-run/inspect? 0=blind trust, 5=some checking, 10=rigorous verification.",
    "decomposition": "Did the human break the problem into ordered steps vs one mega-prompt? 0=single dump, 5=loose, 10=clear sequencing.",
    "intent_fidelity": "Does the FINAL code satisfy everything the human asked for across the whole conversation? 0=ignores stated wants, 10=fully satisfies.",
    "trap_coverage": "Of the listed TRAP requirements, how many did the final solution + conversation actually handle? Score proportional to coverage. If no traps listed, return 5.",
}


class LLMJudge:
    def __init__(self, api_key: str, samples: int = 1):
        self._key = api_key
        self._samples = samples

    def judge(self, ctx: ScoringContext) -> dict:
        prompt = _build_prompt(ctx)
        results: list[dict] = []
        for _ in range(self._samples):
            parsed = self._call(prompt)
            if parsed:
                results.append(parsed)
        if not results:
            return {}
        # Median per signal across samples (stability), clamp 0..10.
        out: dict = {}
        for name in LLM_SIGNALS:
            scores = [float(r[name]["score"]) for r in results if name in r and "score" in r[name]]
            if not scores:
                continue
            median = statistics.median(scores)
            first = next((r[name] for r in results if name in r), {})
            out[name] = {
                "score": max(0.0, min(10.0, median)),
                "reason": str(first.get("reason", ""))[:300],
                "evidence": [str(e)[:160] for e in (first.get("evidence") or [])][:3],
            }
        return out

    def _call(self, prompt: str) -> dict | None:
        try:
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": self._key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": settings.SCORING_MODEL, "max_tokens": 2048,
                      "temperature": 0, "messages": [{"role": "user", "content": prompt}]},
                timeout=120.0,
            )
            if resp.status_code != 200:
                logger.error("LLM judge HTTP %s: %s", resp.status_code, resp.text[:300])
                return None
            text = "".join(b["text"] for b in resp.json().get("content", []) if b.get("type") == "text").strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            return json.loads(text.strip())
        except (json.JSONDecodeError, KeyError, httpx.HTTPError):
            logger.exception("LLM judge call failed")
            return None


def _build_prompt(ctx: ScoringContext) -> str:
    turns = ctx.turns[:40]
    transcript = "\n".join(
        f"[{t.get('role', '?')}] {(t.get('content') or '')[:800]}" for t in turns
    ) or "(no transcript)"
    files = "\n".join(
        f"--- {f.get('path', '?')} ---\n{(f.get('content') or '')[:3000]}"
        for f in ctx.code_snapshot[:15]
    ) or "(no files)"
    traps = "\n".join(f"- {t.description}" for t in ctx.config.traps) or "(none)"
    rubric = "\n".join(f"- {k}: {v}" for k, v in LLM_SIGNALS.items())
    keys = ", ".join(f'"{k}"' for k in LLM_SIGNALS)
    return f"""You are scoring how well a developer DIRECTED an AI coding agent to solve a challenge.
Score each dimension 0-10 using these anchored definitions:
{rubric}

## Challenge
{ctx.challenge.get('problem_statement_md', 'N/A')[:2000]}

## TRAP requirements (subtle things a careless one-shot misses)
{traps}

## Conversation (human <-> AI)
{transcript}

## Final code
{files}

Respond with ONLY valid JSON, one object whose keys are exactly: {keys}.
Each value is {{"score": <0-10>, "reason": "<short>", "evidence": ["<quote>", ...]}}.
Base every score on quotes from the conversation or code; if you cannot find evidence, score low."""
