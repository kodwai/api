"""Scoring engine for developer challenge submissions.

Two-phase scoring:
  Phase 1 — Objective (70% weight): test results, code quality, time, iteration analysis
  Phase 2 — Analytical (30% weight): LLM analysis using developer's API key (skipped if no key)
"""
from __future__ import annotations

import json
import logging
import re
import secrets

import httpx

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.services.encryption_service import decrypt_api_key

logger = logging.getLogger(__name__)


# ── Public entry point ──


def score_submission(submission_id: str) -> None:
    """Score a submission end-to-end. Called from a background thread."""
    try:
        _run_scoring(submission_id)
    except Exception:
        logger.exception("Scoring failed for submission %s", submission_id)
        try:
            execute(
                "UPDATE submissions SET status = 'error', updated_at = datetime('now') WHERE id = ?",
                (submission_id,),
            )
        except Exception:
            pass


# ── Orchestrator ──


def _run_scoring(submission_id: str) -> None:
    submission = fetch_one("SELECT * FROM submissions WHERE id = ?", (submission_id,))
    if submission is None:
        return

    challenge = fetch_one("SELECT * FROM challenges WHERE id = ?", (submission["challenge_id"],))
    if challenge is None:
        return

    # Parse stored JSON fields
    test_results = _parse_json(submission.get("test_results"))
    code_snapshot = _parse_json(submission.get("code_snapshot")) or []
    git_log = _parse_json(submission.get("git_log")) or []
    agent_trace = _parse_json(submission.get("agent_trace"))

    # ── Phase 1: Objective scoring ──
    obj = _objective_score(test_results, code_snapshot, git_log, submission, challenge)

    # ── Phase 2: Analytical scoring (if developer has an API key) ──
    analytical = _analytical_score(submission, challenge, code_snapshot, git_log, agent_trace)

    # ── Check if late ──
    time_ms = submission.get("time_taken_ms") or 0
    limit_ms = (challenge.get("time_limit_minutes") or 60) * 60 * 1000
    is_late = time_ms > limit_ms if time_ms > 0 else False
    late_penalty = 0.0
    if is_late:
        over_ratio = time_ms / limit_ms
        if over_ratio <= 1.25:
            late_penalty = 10.0  # Up to 25% over: -10 points
        elif over_ratio <= 1.5:
            late_penalty = 20.0  # Up to 50% over: -20 points
        else:
            late_penalty = 30.0  # More than 50% over: -30 points

    # ── Combine ──
    if analytical:
        overall = round(obj["total"] * 0.7 + analytical["total"] * 0.3, 1)
        analytical_skipped = False
    else:
        overall = round(obj["total"], 1)
        analytical_skipped = True

    # Leaderboard eligibility: a submission only counts toward leaderboards when the
    # AI/analytical phase contributed. That phase runs only when the developer added
    # their own Claude API key; without it the score is objective-only (non-AI) and
    # not comparable to AI-scored submissions, so it is hidden from every leaderboard.
    leaderboard_eligible = 0 if analytical_skipped else 1

    overall = min(overall, 100.0)

    # Apply late penalty
    if is_late:
        overall = max(0, round(overall - late_penalty, 1))

    breakdown = {
        "objective": obj,
        "analytical": analytical,
        "analytical_skipped": analytical_skipped,
        "leaderboard_eligible": bool(leaderboard_eligible),
        "is_late": is_late,
        "late_penalty": late_penalty if is_late else 0,
        "overall": overall,
    }

    # ── Store results ──
    execute(
        """UPDATE submissions SET
              status = 'scored',
              score = ?,
              score_breakdown = ?,
              leaderboard_eligible = ?,
              scored_at = datetime('now'),
              updated_at = datetime('now')
           WHERE id = ?""",
        (overall, json.dumps(breakdown), leaderboard_eligible, submission_id),
    )

    # Update challenge stats
    challenge_id = submission["challenge_id"]
    execute(
        """UPDATE challenges SET
              submission_count = (SELECT COUNT(*) FROM submissions WHERE challenge_id = ? AND status = 'scored'),
              avg_score = (SELECT AVG(score) FROM submissions WHERE challenge_id = ? AND status = 'scored'),
              updated_at = datetime('now')
           WHERE id = ?""",
        (challenge_id, challenge_id, challenge_id),
    )

    # Update developer profile stats
    user_id = submission["user_id"]

    # Find most-used agent
    agent_row = fetch_one(
        """SELECT agent_used, COUNT(*) as cnt FROM submissions
           WHERE user_id = ? AND status = 'scored' AND agent_used IS NOT NULL
           GROUP BY agent_used ORDER BY cnt DESC LIMIT 1""",
        (user_id,),
    )
    preferred_agent = agent_row["agent_used"] if agent_row else None

    # Weighted total score: easy=1x, medium=1.5x, hard=2x
    execute(
        """UPDATE developer_profiles SET
              challenges_completed = (SELECT COUNT(DISTINCT challenge_id) FROM submissions WHERE user_id = ? AND status = 'scored'),
              total_score = COALESCE(
                (SELECT SUM(best.weighted_score) / SUM(best.weight) FROM (
                  SELECT s.challenge_id,
                         MAX(s.score) as score,
                         CASE c.difficulty WHEN 'easy' THEN 1.0 WHEN 'medium' THEN 1.5 WHEN 'hard' THEN 2.0 ELSE 1.0 END as weight,
                         MAX(s.score) * CASE c.difficulty WHEN 'easy' THEN 1.0 WHEN 'medium' THEN 1.5 WHEN 'hard' THEN 2.0 ELSE 1.0 END as weighted_score
                  FROM submissions s
                  JOIN challenges c ON s.challenge_id = c.id
                  WHERE s.user_id = ? AND s.status = 'scored' AND s.leaderboard_eligible = 1
                  GROUP BY s.challenge_id
                ) best), 0),
              preferred_agent = ?,
              last_submission_at = datetime('now'),
              updated_at = datetime('now')
           WHERE user_id = ?""",
        (user_id, user_id, preferred_agent, user_id),
    )

    # Recompute global ranks for all developers
    _recompute_ranks()

    # Update leaderboard — keep best score per user per challenge.
    # Only eligible submissions (AI-scored) ever reach a leaderboard; an ineligible
    # submission never creates or overwrites an entry, so any existing eligible entry
    # for this challenge is preserved.
    user_id = submission["user_id"]
    challenge_id = submission["challenge_id"]
    if leaderboard_eligible:
        existing_entry = fetch_one(
            "SELECT id, score FROM leaderboard_entries WHERE user_id = ? AND challenge_id = ?",
            (user_id, challenge_id),
        )
        if existing_entry is None:
            entry_id = secrets.token_hex(16)
            execute(
                """INSERT INTO leaderboard_entries (id, user_id, challenge_id, submission_id, score, agent_used, time_taken_ms, submitted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (entry_id, user_id, challenge_id, submission_id, overall,
                 submission.get("agent_used"), submission.get("time_taken_ms")),
            )
        elif overall > existing_entry["score"]:
            execute(
                """UPDATE leaderboard_entries SET
                      submission_id = ?, score = ?, agent_used = ?, time_taken_ms = ?,
                      submitted_at = datetime('now')
                   WHERE id = ?""",
                (submission_id, overall, submission.get("agent_used"),
                 submission.get("time_taken_ms"), existing_entry["id"]),
            )

    # Evaluate badges
    try:
        from app.services.badge_engine import evaluate_badges
        new_badges = evaluate_badges(user_id, submission_id)
        if new_badges:
            logger.info("Awarded %d badges to user %s: %s",
                        len(new_badges), user_id, [b["slug"] for b in new_badges])
    except Exception:
        logger.exception("Badge evaluation failed for user %s", user_id)

    logger.info("Scored submission %s: %.1f (objective=%.1f, analytical=%s)",
                submission_id, overall, obj["total"],
                f"{analytical['total']:.1f}" if analytical else "skipped")


# ── Phase 1: Objective scoring ──


def _objective_score(
    test_results: dict | None,
    code_snapshot: list[dict],
    git_log: list[dict],
    submission: dict,
    challenge: dict,
) -> dict:
    """Deterministic scoring: tests, code quality, time, iteration."""

    # 1. Test pass rate (0-30 points)
    test_score = 0.0
    test_detail = "no tests"
    if test_results and test_results.get("total", 0) > 0:
        pass_rate = test_results["passed"] / test_results["total"]
        test_score = round(pass_rate * 30, 1)
        test_detail = f"{test_results['passed']}/{test_results['total']} passed"
    elif not test_results:
        # No test results submitted — can't verify correctness, give 0
        test_score = 0.0
        test_detail = "no test results submitted"

    # 2. Code quality — lint-like analysis (0-20 points)
    lint_score, lint_detail = _lint_analysis(code_snapshot)

    # 3. Complexity analysis (0-10 points)
    complexity_score, complexity_detail = _complexity_analysis(code_snapshot)

    # 4. Time efficiency (0-15 points)
    time_score, time_detail = _time_score(submission, challenge)

    # 5. Iteration efficiency from git (0-10 points)
    iteration_score, iteration_detail = _iteration_analysis(git_log)

    # Total capped at 85 (leaves room for analytical to push above)
    total = min(test_score + lint_score + complexity_score + time_score + iteration_score, 100.0)

    return {
        "total": round(total, 1),
        "dimensions": [
            {"name": "Test Pass Rate", "score": test_score, "max": 30, "detail": test_detail},
            {"name": "Code Quality", "score": lint_score, "max": 20, "detail": lint_detail},
            {"name": "Complexity", "score": complexity_score, "max": 10, "detail": complexity_detail},
            {"name": "Time Efficiency", "score": time_score, "max": 15, "detail": time_detail},
            {"name": "Iteration", "score": iteration_score, "max": 10, "detail": iteration_detail},
        ],
    }


def _lint_analysis(code_snapshot: list[dict]) -> tuple[float, str]:
    """Analyze code quality from text — no execution needed."""
    if not code_snapshot:
        return 10.0, "no code files"

    total_issues = 0
    total_lines = 0
    files_checked = 0

    for file in code_snapshot:
        content = file.get("content", "")
        path = file.get("path", "")
        if not content or not _is_code_file(path):
            continue

        files_checked += 1
        lines = content.split("\n")
        total_lines += len(lines)

        for line in lines:
            stripped = line.rstrip()
            # Trailing whitespace
            if stripped != line.rstrip("\n") and len(line) - len(stripped) > 0:
                total_issues += 0.1
            # Very long lines (>120 chars)
            if len(stripped) > 120:
                total_issues += 0.3
            # console.log / print debugging left in
            if re.search(r'\bconsole\.(log|debug)\b', stripped) or re.search(r'\bprint\s*\(', stripped):
                total_issues += 0.5
            # TODO/FIXME/HACK comments
            if re.search(r'\b(TODO|FIXME|HACK|XXX)\b', stripped):
                total_issues += 0.3

        # Check for empty catch blocks
        if re.search(r'catch\s*\([^)]*\)\s*\{\s*\}', content):
            total_issues += 2
        # Check for unused imports (basic: import but name not used elsewhere)
        # Too complex for regex — skip

    if total_lines == 0:
        return 10.0, "no code lines"

    # Score: fewer issues = higher score
    issues_per_100_lines = (total_issues / total_lines) * 100
    if issues_per_100_lines <= 1:
        score = 20.0
    elif issues_per_100_lines <= 3:
        score = 16.0
    elif issues_per_100_lines <= 6:
        score = 12.0
    elif issues_per_100_lines <= 10:
        score = 8.0
    else:
        score = 4.0

    return score, f"{files_checked} files, {total_lines} lines, ~{total_issues:.0f} issues"


def _complexity_analysis(code_snapshot: list[dict]) -> tuple[float, str]:
    """Estimate code complexity from text."""
    if not code_snapshot:
        return 5.0, "no code files"

    total_functions = 0
    long_functions = 0
    max_nesting = 0

    for file in code_snapshot:
        content = file.get("content", "")
        path = file.get("path", "")
        if not content or not _is_code_file(path):
            continue

        # Count functions
        fn_matches = re.findall(
            r'(?:function\s+\w+|(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:\([^)]*\)|[a-zA-Z_]\w*)\s*=>|def\s+\w+)',
            content,
        )
        total_functions += len(fn_matches)

        # Estimate function lengths by splitting on function boundaries
        lines = content.split("\n")
        current_depth = 0
        fn_line_count = 0
        in_function = False

        for line in lines:
            opens = line.count("{") + line.count("(") * 0
            closes = line.count("}") + line.count(")") * 0
            current_depth += opens - closes
            max_nesting = max(max_nesting, current_depth)

            if any(m in line for m in ["function ", "def ", "=>"]):
                if in_function and fn_line_count > 50:
                    long_functions += 1
                in_function = True
                fn_line_count = 0
            if in_function:
                fn_line_count += 1

        if in_function and fn_line_count > 50:
            long_functions += 1

    # Score based on complexity metrics
    score = 10.0
    if max_nesting > 8:
        score -= 3
    elif max_nesting > 5:
        score -= 1
    if total_functions > 0 and long_functions / total_functions > 0.3:
        score -= 3
    elif total_functions > 0 and long_functions / total_functions > 0.1:
        score -= 1

    score = max(score, 2.0)

    return round(score, 1), f"{total_functions} functions, {long_functions} long (>50 lines), max nesting {max_nesting}"


def _time_score(submission: dict, challenge: dict) -> tuple[float, str]:
    """Score based on completion time vs time limit."""
    time_ms = submission.get("time_taken_ms") or 0
    limit_ms = (challenge.get("time_limit_minutes") or 60) * 60 * 1000

    if time_ms <= 0:
        return 7.5, "no time data"

    ratio = time_ms / limit_ms

    if ratio <= 0.3:
        score = 15.0
    elif ratio <= 0.5:
        score = 13.0
    elif ratio <= 0.7:
        score = 10.0
    elif ratio <= 0.9:
        score = 7.0
    elif ratio <= 1.0:
        score = 5.0
    elif ratio <= 1.5:
        score = 2.0  # Moderately over time
    else:
        score = 0.0  # Way over time limit

    minutes = round(time_ms / 60000)
    limit_min = challenge.get("time_limit_minutes", 60)

    return score, f"{minutes}/{limit_min} min ({ratio:.0%} of limit)"


def _iteration_analysis(git_log: list[dict]) -> tuple[float, str]:
    """Score based on commit patterns — incremental is better."""
    if not git_log or len(git_log) <= 1:
        return 5.0, f"{len(git_log)} commits (initial only)"

    # Exclude the initial commit
    commits = [c for c in git_log if "initial" not in (c.get("message", "")).lower()]
    num_commits = len(commits)

    if num_commits == 0:
        return 3.0, "no commits beyond initial"
    elif num_commits == 1:
        return 5.0, "1 commit (single big push)"
    elif num_commits <= 3:
        score = 7.0
    elif num_commits <= 8:
        score = 9.0
    else:
        score = 10.0

    return score, f"{num_commits} incremental commits"


# ── Phase 2: Analytical scoring ──


def _analytical_score(
    submission: dict,
    challenge: dict,
    code_snapshot: list[dict],
    git_log: list[dict],
    agent_trace: dict | None,
) -> dict | None:
    """LLM-based analysis using the developer's own API key. Returns None if no key."""

    # Find developer's API key
    user_id = submission["user_id"]
    api_key_row = fetch_one(
        "SELECT encrypted_key, key_iv FROM api_keys WHERE user_id = ? AND is_active = 1 LIMIT 1",
        (user_id,),
    )
    if api_key_row is None:
        logger.info("No API key for user %s — skipping analytical scoring", user_id)
        return None

    try:
        real_api_key = decrypt_api_key(
            api_key_row["encrypted_key"],
            api_key_row["key_iv"],
            settings.ENCRYPTION_KEY,
        )
    except Exception:
        logger.exception("Failed to decrypt API key for user %s", user_id)
        return None

    # Build prompt
    prompt = _build_analytical_prompt(challenge, code_snapshot, git_log, agent_trace, submission)

    # Call Anthropic API
    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": real_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.SCORING_MODEL,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120.0,
        )

        if response.status_code != 200:
            logger.error("Anthropic API returned %s for analytical scoring: %s",
                         response.status_code, response.text[:300])
            return None

        body = response.json()
        content_text = ""
        for block in body.get("content", []):
            if block.get("type") == "text":
                content_text += block["text"]

        # Strip markdown fences
        text = content_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]

        score_data = json.loads(text.strip())

        # Normalize to 0-100 scale
        dimensions = score_data.get("dimensions", [])
        total = 0.0
        for dim in dimensions:
            total += float(dim.get("score", 0))

        max_possible = sum(float(d.get("max_score", 10)) for d in dimensions) if dimensions else 30
        normalized = (total / max_possible * 100) if max_possible > 0 else 50

        return {
            "total": round(min(normalized, 100), 1),
            "dimensions": dimensions,
            "summary": score_data.get("summary", ""),
            "strengths": score_data.get("strengths", []),
            "weaknesses": score_data.get("weaknesses", []),
        }

    except json.JSONDecodeError:
        logger.error("Failed to parse analytical scoring JSON for submission %s", submission["id"])
        return None
    except Exception:
        logger.exception("Analytical scoring failed for submission %s", submission["id"])
        return None


def _build_analytical_prompt(
    challenge: dict,
    code_snapshot: list[dict],
    git_log: list[dict],
    agent_trace: dict | None,
    submission: dict,
) -> str:
    """Build the LLM prompt for analytical evaluation."""

    # Format code files
    files_text = ""
    for f in code_snapshot[:20]:  # Cap at 20 files
        content = f.get("content", "")[:5000]  # Cap file size
        files_text += f"\n--- {f.get('path', 'unknown')} ---\n{content}\n"

    # Format agent trace
    trace_text = "(no agent trace available)"
    if agent_trace and agent_trace.get("turns"):
        turns = agent_trace["turns"][:30]  # Cap at 30 turns
        trace_lines = []
        for t in turns:
            role = t.get("role", "?")
            content = t.get("content", "")[:500]
            trace_lines.append(f"[{role}] {content}")
        trace_text = "\n".join(trace_lines)

    # Format git history
    git_text = "(no git history)"
    if git_log:
        git_text = "\n".join(
            f"  {c.get('message', '?')}" for c in git_log[:20]
        )

    time_min = round((submission.get("time_taken_ms") or 0) / 60000)

    return f"""You are an expert code reviewer evaluating a developer's solution to a coding challenge.
Evaluate how well they solved the problem AND how effectively they used their AI coding agent.

## Challenge
Title: {challenge.get("title", "N/A")}
Difficulty: {challenge.get("difficulty", "N/A")}
Problem:
{challenge.get("problem_statement_md", "N/A")}

## Submitted Code
{files_text}

## Git History
{git_text}

## AI Agent Interaction Trace
Agent: {submission.get("agent_used", "unknown")}
{trace_text}

## Metadata
Time taken: {time_min} minutes (limit: {challenge.get("time_limit_minutes", 60)} min)

## Evaluation
Score each dimension from 0-10 with justification:
1. Problem Solving — Did they understand and address all requirements?
2. Code Quality — Is the code clean, readable, and well-structured?
3. Agent Collaboration — Did they use the AI agent effectively? Good prompts, appropriate delegation, caught errors?

Respond with ONLY valid JSON:
{{
  "dimensions": [
    {{"name": "Problem Solving", "score": 8, "max_score": 10, "justification": "reason"}},
    {{"name": "Code Quality", "score": 7, "max_score": 10, "justification": "reason"}},
    {{"name": "Agent Collaboration", "score": 8, "max_score": 10, "justification": "reason"}}
  ],
  "summary": "2-3 sentence overall assessment",
  "strengths": ["strength 1", "strength 2"],
  "weaknesses": ["weakness 1"]
}}"""


# ── Utilities ──


def _is_code_file(path: str) -> bool:
    """Check if a file is a code file worth analyzing."""
    code_extensions = {
        ".js", ".ts", ".jsx", ".tsx", ".py", ".rb", ".go", ".rs",
        ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".cs",
        ".php", ".vue", ".svelte", ".astro",
    }
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return ext in code_extensions


def _recompute_ranks() -> None:
    """Recompute global rank based on total_score.

    Only developers with at least one leaderboard-eligible (AI-scored) submission are
    ranked; everyone else has their rank cleared so it never surfaces on a leaderboard
    or share card.
    """
    execute(
        """UPDATE developer_profiles SET rank = NULL
           WHERE user_id NOT IN (
               SELECT DISTINCT user_id FROM submissions
               WHERE status = 'scored' AND leaderboard_eligible = 1
           )""",
    )
    profiles = fetch_all(
        """SELECT user_id FROM developer_profiles
           WHERE user_id IN (
               SELECT DISTINCT user_id FROM submissions
               WHERE status = 'scored' AND leaderboard_eligible = 1
           )
           ORDER BY total_score DESC""",
    )
    for i, p in enumerate(profiles):
        execute(
            "UPDATE developer_profiles SET rank = ? WHERE user_id = ?",
            (i + 1, p["user_id"]),
        )


def _parse_json(value: str | None) -> dict | list | None:
    """Safely parse a JSON string."""
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
