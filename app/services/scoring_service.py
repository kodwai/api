from __future__ import annotations

import json
import logging
import secrets

import httpx

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.services.encryption_service import decrypt_api_key

logger = logging.getLogger(__name__)


def _build_scoring_prompt(
    session: dict,
    project: dict,
    events: list[dict],
    final_files: list[dict],
    rubric: list[dict],
) -> str:
    """Construct the scoring prompt sent to the AI model."""

    # Format events into a readable transcript
    transcript_lines: list[str] = []
    for ev in events:
        ts = ev.get("timestamp", "")
        etype = ev.get("event_type", "")
        data = ev.get("data", "")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (ValueError, TypeError):
                pass
        transcript_lines.append(f"[{ts}] {etype}: {json.dumps(data, default=str)}")

    transcript = "\n".join(transcript_lines) if transcript_lines else "(no events recorded)"

    # Format final files
    files_section_parts: list[str] = []
    for f in final_files:
        path = f.get("file_path", "unknown")
        content = f.get("content", "")
        files_section_parts.append(f"--- {path} ---\n{content}\n")
    files_section = "\n".join(files_section_parts) if files_section_parts else "(no final files)"

    # Format rubric dimensions
    rubric_lines: list[str] = []
    for dim in rubric:
        name = dim.get("dimension", dim.get("name", "Unknown"))
        weight = dim.get("weight", 1)
        desc = dim.get("description", "")
        rubric_lines.append(f"- {name} (weight: {weight}): {desc}")
    rubric_section = "\n".join(rubric_lines) if rubric_lines else "(no rubric defined)"

    return f"""You are an expert technical interviewer and code reviewer. Evaluate the following coding interview session.

## Project
Title: {project.get("title", "N/A")}
Problem Statement:
{project.get("problem_statement_md", "N/A")}

Difficulty: {project.get("difficulty", "N/A")}
Time Limit: {project.get("time_limit_minutes", "N/A")} minutes

## Rubric Dimensions
{rubric_section}

## Session Info
Candidate: {session.get("candidate_name", "N/A")}
Status: {session.get("status", "N/A")}
Started: {session.get("started_at", "N/A")}
Ended: {session.get("ended_at", "N/A")}
Total Cost: ${session.get("total_cost_usd", 0) or 0:.4f}
Total Tokens: {session.get("total_tokens", 0) or 0}

## Session Transcript (chronological events)
{transcript}

## Final Code Files
{files_section}

## Evaluation Instructions
Evaluate the candidate on:
1. Each rubric dimension listed above (if any)
2. Code quality of the final files
3. Problem-solving approach (how they broke down the problem)
4. AI collaboration effectiveness (how well they used the AI assistant)
5. Time management

For each dimension, provide a score from 0-10 and a brief justification.

Respond with ONLY valid JSON in this exact format:
{{
  "dimensions": [
    {{"name": "dimension name", "score": 8, "max_score": 10, "justification": "brief reason"}},
    ...
  ],
  "overall_score": 7.5,
  "summary": "2-3 sentence overall assessment",
  "strengths": ["strength 1", "strength 2"],
  "weaknesses": ["weakness 1", "weakness 2"]
}}"""


def trigger_ai_scoring(session_id: str) -> dict | None:
    """Run the AI scoring pipeline for a completed session.

    Returns the parsed score dict on success, or None on failure/skip.
    """
    try:
        return _run_scoring_pipeline(session_id)
    except Exception:
        logger.exception("AI scoring pipeline failed for session %s", session_id)
        return None


def _run_scoring_pipeline(session_id: str) -> dict | None:
    """Internal: fetch data, call API, store results."""

    # 1. Fetch session
    session = fetch_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    if session is None:
        logger.error("Session %s not found for scoring", session_id)
        return None

    # 2. Fetch and decrypt the session's API key
    api_key_row = fetch_one(
        "SELECT encrypted_key, key_iv FROM api_keys WHERE id = ?",
        (session["api_key_id"],),
    )
    if api_key_row is None:
        logger.error("API key not found for session %s (api_key_id=%s)", session_id, session["api_key_id"])
        return None

    real_api_key = decrypt_api_key(
        api_key_row["encrypted_key"],
        api_key_row["key_iv"],
        settings.ENCRYPTION_KEY,
    )

    # 3. Fetch project (including rubric)
    project = fetch_one("SELECT * FROM projects WHERE id = ?", (session["project_id"],))
    if project is None:
        logger.error("Project not found for session %s", session_id)
        return None

    # 3. Parse rubric
    rubric: list[dict] = []
    if project.get("rubric"):
        try:
            rubric = json.loads(project["rubric"]) if isinstance(project["rubric"], str) else project["rubric"]
        except (ValueError, TypeError):
            logger.warning("Could not parse rubric for project %s", project["id"])

    # 4. Fetch all session events
    events = fetch_all(
        "SELECT * FROM session_events WHERE session_id = ? ORDER BY timestamp ASC",
        (session_id,),
    )

    # 5. Fetch final files (prefer final_files table, fall back to latest file_changes)
    final_files = fetch_all(
        "SELECT file_path, content FROM final_files WHERE session_id = ?",
        (session_id,),
    )
    if not final_files:
        # Fall back: get the latest version of each file from file_changes
        final_files = fetch_all(
            """SELECT fc.file_path, fc.content
               FROM file_changes fc
               INNER JOIN (
                   SELECT file_path, MAX(timestamp) AS max_ts
                   FROM file_changes
                   WHERE session_id = ?
                   GROUP BY file_path
               ) latest ON fc.file_path = latest.file_path AND fc.timestamp = latest.max_ts
               WHERE fc.session_id = ? AND fc.change_type != 'delete'""",
            (session_id, session_id),
        )

    # 6. Build prompt
    prompt = _build_scoring_prompt(session, project, events, final_files, rubric)

    # 7. Call Anthropic API
    logger.info("Calling AI scoring for session %s using model %s", session_id, settings.SCORING_MODEL)

    response = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": real_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": settings.SCORING_MODEL,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=300.0,
    )

    if response.status_code != 200:
        logger.error(
            "Anthropic API returned %s for session %s: %s",
            response.status_code,
            session_id,
            response.text[:500],
        )
        return None

    # 8. Parse response
    body = response.json()
    content_text = ""
    for block in body.get("content", []):
        if block.get("type") == "text":
            content_text += block["text"]

    if not content_text:
        logger.error("Empty response from Anthropic API for session %s", session_id)
        return None

    # Strip markdown code fences if present
    text = content_text.strip()
    if text.startswith("```"):
        # Remove opening fence (e.g. ```json)
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        score_data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse AI scoring JSON for session %s: %.200s", session_id, text)
        return None

    # 9. Validate and store
    dimensions = score_data.get("dimensions", [])
    overall_score = float(score_data.get("overall_score", 0))
    summary = score_data.get("summary", "")
    strengths = score_data.get("strengths", [])
    weaknesses = score_data.get("weaknesses", [])

    score_id = secrets.token_hex(16)

    execute(
        """INSERT INTO scores (id, session_id, score_type, scorer_id, dimensions, overall_score, summary, strengths, weaknesses)
           VALUES (?, ?, 'ai', NULL, ?, ?, ?, ?, ?)""",
        (
            score_id,
            session_id,
            json.dumps(dimensions),
            overall_score,
            summary,
            json.dumps(strengths),
            json.dumps(weaknesses),
        ),
    )

    logger.info("AI scoring completed for session %s — overall_score=%.1f", session_id, overall_score)
    return score_data
