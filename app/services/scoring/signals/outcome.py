from __future__ import annotations

import re

from app.services.scoring.models import ScoringContext, SignalResult

_CODE_EXT = {
    ".js", ".ts", ".jsx", ".tsx", ".py", ".rb", ".go", ".rs", ".java", ".kt",
    ".swift", ".c", ".cpp", ".h", ".cs", ".php", ".vue", ".svelte", ".astro",
}


def _is_code_file(path: str) -> bool:
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return ext in _CODE_EXT


def tests(ctx: ScoringContext) -> SignalResult:
    tr = ctx.test_results
    if not tr or tr.get("total", 0) <= 0:
        return SignalResult(0.0, "no test results submitted", [])
    rate = tr["passed"] / tr["total"]
    return SignalResult(round(rate, 3), f"{tr['passed']}/{tr['total']} tests passed",
                        [tr.get("output", "")[:300]] if tr.get("output") else [])


def code_quality(ctx: ScoringContext) -> SignalResult:
    files = [f for f in ctx.code_snapshot if f.get("content") and _is_code_file(f.get("path", ""))]
    if not files:
        return SignalResult(0.5, "no code files to analyze")
    issues = 0.0
    total_lines = 0
    for f in files:
        content = f["content"]
        for line in content.split("\n"):
            stripped = line.rstrip()
            total_lines += 1
            if len(stripped) > 120:
                issues += 0.3
            if re.search(r"\bconsole\.(log|debug)\b", stripped) or re.search(r"\bprint\s*\(", stripped):
                issues += 0.5
            if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", stripped):
                issues += 0.3
        if re.search(r"catch\s*\([^)]*\)\s*\{\s*\}", content):
            issues += 2
    if total_lines == 0:
        return SignalResult(0.5, "no code lines")
    per100 = (issues / total_lines) * 100
    value = max(0.0, min(1.0, 1.0 - per100 / 10.0))  # 0 issues/100 -> 1.0, 10/100 -> 0.0
    return SignalResult(round(value, 3), f"{len(files)} files, ~{issues:.0f} issues / {total_lines} lines")


def complexity(ctx: ScoringContext) -> SignalResult:
    files = [f for f in ctx.code_snapshot if f.get("content") and _is_code_file(f.get("path", ""))]
    if not files:
        return SignalResult(0.5, "no code files")
    max_nesting = 0
    for f in files:
        depth = 0
        for ch in f["content"]:
            if ch == "{":
                depth += 1
                max_nesting = max(max_nesting, depth)
            elif ch == "}":
                depth = max(0, depth - 1)
    if max_nesting > 8:
        value = 0.4
    elif max_nesting > 5:
        value = 0.7
    else:
        value = 1.0
    return SignalResult(value, f"max nesting depth {max_nesting}")
