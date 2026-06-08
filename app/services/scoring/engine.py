from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one
from app.services.encryption_service import decrypt_api_key
from app.services.scoring.config import resolve_config
from app.services.scoring.llm import LLMJudge
from app.services.scoring.models import AxisResult, ScoreBreakdown, ScoringContext
from app.services.scoring.registry import get_signal

logger = logging.getLogger(__name__)


def compute_streak(current_streak: int | None, last_submission_at: str | None) -> int:
    """New consecutive-day streak given the PREVIOUS last_submission_at (UTC).
    First/none -> 1; same UTC day -> unchanged (>=1); yesterday -> +1; gap -> 1."""
    today = datetime.now(timezone.utc).date()
    if not last_submission_at:
        return 1
    try:
        last = datetime.fromisoformat(str(last_submission_at).replace("Z", "")).date()
    except Exception:
        return 1
    delta = (today - last).days
    if delta <= 0:
        return current_streak if current_streak and current_streak > 0 else 1
    if delta == 1:
        return (current_streak or 0) + 1
    return 1

_CHALLENGE_RATING = {"easy": 1000, "medium": 1300, "hard": 1600}


def update_rating(current_rating: int | None, difficulty: str | None, score: float | None, k: int = 24) -> int:
    """ELO-style update: the challenge (by difficulty) is the opponent, score/100 the outcome."""
    r = current_rating if current_rating else 1000
    cr = _CHALLENGE_RATING.get((difficulty or "").lower(), 1300)
    expected = 1.0 / (1.0 + 10 ** ((cr - r) / 400.0))
    outcome = max(0.0, min(1.0, (score or 0) / 100.0))
    return max(100, round(r + k * (outcome - expected)))


def _bump_skill_rating(user_id: str, dimension: str, key: str | None, difficulty: str | None, score: float | None) -> None:
    """Upsert a per-dimension mastery rating (ELO) for the given key (category or model)."""
    if not key:
        return
    row = fetch_one(
        "SELECT rating FROM user_skill_ratings WHERE user_id = ? AND dimension = ? AND key = ?",
        (user_id, dimension, key),
    )
    new = update_rating(row["rating"] if row else 1000, difficulty, score)
    execute(
        """INSERT INTO user_skill_ratings (user_id, dimension, key, rating, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(user_id, dimension, key) DO UPDATE SET rating = excluded.rating, updated_at = excluded.updated_at""",
        (user_id, dimension, key, new),
    )


SCORING_VERSION = 2


def score_submission(submission_id: str) -> None:
    """Score a submission end-to-end. Called from a background thread."""
    try:
        _run(submission_id)
    except Exception:
        logger.exception("Scoring failed for submission %s", submission_id)
        try:
            execute("UPDATE submissions SET status='error', updated_at=datetime('now') WHERE id=?",
                    (submission_id,))
        except Exception:
            pass


def _parse(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _resolve_api_key(submission: dict) -> str | None:
    """Resolve which Anthropic key pays for this submission's AI scoring.

    Driven by ``submission.key_source`` (set at submit time):
      'platform' → the platform's own key (free tier).
      'user'     → the developer's connected key.
      NULL       → legacy rows: fall back to the developer's connected key.
    Returns None when no usable key is configured (AI scoring is then skipped).
    """
    if submission.get("key_source") == "platform":
        return settings.PLATFORM_ANTHROPIC_API_KEY or None
    key_row = fetch_one(
        "SELECT encrypted_key, key_iv FROM api_keys WHERE user_id=? AND is_active=1 LIMIT 1",
        (submission["user_id"],),
    )
    if key_row:
        return decrypt_api_key(key_row["encrypted_key"], key_row["key_iv"], settings.ENCRYPTION_KEY)
    return None


def _load_context(submission: dict, challenge: dict) -> ScoringContext:
    cfg = resolve_config(challenge.get("scoring_config"))
    ctx = ScoringContext(
        submission=submission,
        challenge=challenge,
        config=cfg,
        test_results=_parse(submission.get("test_results")),
        code_snapshot=_parse(submission.get("code_snapshot")) or [],
        git_log=_parse(submission.get("git_log")) or [],
        agent_trace=_parse(submission.get("agent_trace")),
    )
    # Attach an LLM judge if a key (platform or developer's own) is available.
    try:
        api_key = _resolve_api_key(submission)
    except Exception:
        logger.exception("API key resolution failed for submission %s", submission["id"])
        api_key = None

    if api_key:
        try:
            ctx.has_api_key = True
            ctx.llm = LLMJudge(api_key)
            ctx.judgment = ctx.llm.judge(ctx)
            # If the challenge has a bespoke rubric, run the rubric judge as well.
            if ctx.config.rubric:
                ctx.rubric_judgment = ctx.llm.judge_rubric(ctx, ctx.config.rubric)
        except Exception:
            logger.exception("LLM judging failed for submission %s", submission["id"])
            ctx.judgment = None
            ctx.rubric_judgment = None
    return ctx


def _trace_confidence(ctx: ScoringContext) -> str:
    """Return a transparency-only confidence label for the Direction axis.

    "none"   – no trace at all (agent_trace is None or has no turns).
    "high"   – trace_quality="full" or >=6 user turns when quality is absent.
    "medium" – trace_quality="good" or >=3 user turns when quality is absent.
    "low"    – trace_quality="partial"/"minimal" or <3 user turns.

    This label is informational only; it does NOT alter any score.
    """
    if not ctx.agent_trace:
        return "none"
    turns = ctx.agent_trace.get("turns") or []
    if not turns:
        return "none"

    quality = ctx.agent_trace.get("trace_quality")
    if quality is not None:
        return {"full": "high", "good": "medium", "partial": "low", "minimal": "low"}.get(quality, "low")

    # Derive from meaningful user-turn count when trace_quality is missing.
    user_turns = sum(1 for t in turns if t.get("role") == "user")
    if user_turns >= 6:
        return "high"
    if user_turns >= 3:
        return "medium"
    return "low"


def _assemble(ctx: ScoringContext) -> ScoreBreakdown:
    axes: list[AxisResult] = []
    overall = 0.0

    if ctx.config.rubric:
        # ── Bespoke-rubric layout: direction 45 pts | challenge_rubric 45 pts | lift 10 pts ──
        # Find the direction and lift axes from the profile config (any axis named "direction"
        # or "lift"); everything else is replaced by the challenge_rubric axis.
        direction_cfg = ctx.config.axes.get("direction")
        lift_cfg = ctx.config.axes.get("lift")

        # --- direction axis (rescaled to 45 pts) ---
        if direction_cfg:
            weighted_sum = 0.0
            weight_total = 0.0
            signal_details: list[dict] = []
            for sig_name, weight in direction_cfg.signals.items():
                fn = get_signal(sig_name)
                if fn is None or weight <= 0:
                    continue
                res = fn(ctx)
                if res.skipped:
                    signal_details.append({"name": sig_name, "value": None, "weight": weight,
                                           "reason": res.reason, "evidence": res.evidence, "skipped": True})
                    continue
                weighted_sum += weight * res.value
                weight_total += weight
                signal_details.append({"name": sig_name, "value": res.value, "weight": weight,
                                       "reason": res.reason, "evidence": res.evidence, "skipped": False})
            dir_points = 45.0
            axis_score = round(dir_points * (weighted_sum / weight_total), 2) if weight_total > 0 else 0.0
            overall += axis_score
            axes.append(AxisResult("direction", dir_points, axis_score, signal_details))

        # --- challenge_rubric axis (45 pts) ---
        rubric_points = 45.0
        judgment = ctx.rubric_judgment  # may be None or {}
        if judgment:
            # Compute weighted average of (score/10) across all dims, then × 45.
            weighted_sum = 0.0
            weight_total = 0.0
            signal_details = []
            for dim in ctx.config.rubric:
                name = str(dim.get("name", "")).strip()
                weight = float(dim.get("weight", 1) or 1)
                if weight <= 0:
                    continue
                dim_result = judgment.get(name)
                if dim_result is None:
                    # dimension not scored by LLM — treat as skipped
                    signal_details.append({"name": name, "value": None, "weight": weight,
                                           "reason": "LLM did not return a score for this dimension.",
                                           "evidence": [], "skipped": True})
                    continue
                dim_score_norm = dim_result["score"] / 10.0  # 0..1
                weighted_sum += weight * dim_score_norm
                weight_total += weight
                signal_details.append({
                    "name": name,
                    "value": round(dim_score_norm, 4),
                    "weight": weight,
                    "reason": dim_result.get("justification", ""),
                    "evidence": dim_result.get("evidence", []),
                    "skipped": False,
                })
            rubric_score = round(rubric_points * (weighted_sum / weight_total), 2) if weight_total > 0 else 0.0
        else:
            # No LLM judgment available — axis is skipped
            signal_details = [
                {"name": str(dim.get("name", "")).strip(), "value": None,
                 "weight": float(dim.get("weight", 1) or 1),
                 "reason": "No LLM API key — rubric axis skipped.", "evidence": [], "skipped": True}
                for dim in ctx.config.rubric
            ]
            rubric_score = 0.0
        overall += rubric_score
        axes.append(AxisResult("challenge_rubric", rubric_points, rubric_score, signal_details))

        # --- lift axis (10 pts) ---
        if lift_cfg:
            weighted_sum = 0.0
            weight_total = 0.0
            signal_details = []
            for sig_name, weight in lift_cfg.signals.items():
                fn = get_signal(sig_name)
                if fn is None or weight <= 0:
                    continue
                res = fn(ctx)
                if res.skipped:
                    signal_details.append({"name": sig_name, "value": None, "weight": weight,
                                           "reason": res.reason, "evidence": res.evidence, "skipped": True})
                    continue
                weighted_sum += weight * res.value
                weight_total += weight
                signal_details.append({"name": sig_name, "value": res.value, "weight": weight,
                                       "reason": res.reason, "evidence": res.evidence, "skipped": False})
            lift_points = 10.0
            axis_score = round(lift_points * (weighted_sum / weight_total), 2) if weight_total > 0 else 0.0
            overall += axis_score
            axes.append(AxisResult("lift", lift_points, axis_score, signal_details))

    else:
        # ── Standard layout: profile axes unchanged ──
        for axis_name, axis_cfg in ctx.config.axes.items():
            weighted_sum = 0.0
            weight_total = 0.0
            signal_details: list[dict] = []
            for sig_name, weight in axis_cfg.signals.items():
                fn = get_signal(sig_name)
                if fn is None or weight <= 0:
                    continue
                res = fn(ctx)
                if res.skipped:
                    signal_details.append({"name": sig_name, "value": None, "weight": weight,
                                           "reason": res.reason, "evidence": res.evidence, "skipped": True})
                    continue  # dropped from normalization
                weighted_sum += weight * res.value
                weight_total += weight
                signal_details.append({"name": sig_name, "value": res.value, "weight": weight,
                                       "reason": res.reason, "evidence": res.evidence, "skipped": False})
            axis_score = round(axis_cfg.points * (weighted_sum / weight_total), 2) if weight_total > 0 else 0.0
            overall += axis_score
            axes.append(AxisResult(axis_name, axis_cfg.points, axis_score, signal_details))

    # leaderboard_eligible is the canonical source of truth; supersedes the old
    # score_breakdown.$.analytical_skipped JSON flag written by migration 014.
    # Now also considers rubric judgment (if a rubric is present, rubric_judgment drives eligibility).
    if ctx.config.rubric:
        leaderboard_eligible = (ctx.rubric_judgment is not None and len(ctx.rubric_judgment) > 0)
    else:
        leaderboard_eligible = ctx.judgment is not None and len(ctx.judgment) > 0

    # Static baseline_lift badge (does not change the headline score in v1).
    # ai_baseline is on a 0-100 scale; normalize outcome axis score (raw points) to 0-100 before comparing.
    baseline = ctx.challenge.get("ai_baseline")
    baseline_lift = None
    if baseline is not None:
        outcome_axis = next((a for a in axes if a.name == "outcome"), None)
        artifact = (outcome_axis.score / outcome_axis.points * 100) if (outcome_axis and outcome_axis.points) else 0.0
        delta = round(max(0.0, artifact - float(baseline)), 2)
        baseline_lift = {"beat": artifact > float(baseline), "delta": delta}

    overall = min(round(overall, 1), 100.0)
    breakdown = ScoreBreakdown(SCORING_VERSION, overall, axes,
                               leaderboard_eligible=leaderboard_eligible, baseline_lift=baseline_lift)
    breakdown.trace_quality = (ctx.agent_trace or {}).get("trace_quality")
    breakdown.confidence = _trace_confidence(ctx)
    # Distinguish "no API key" from "key present but the AI judge failed", so the
    # UI can tell the user to re-submit instead of (wrongly) to add a key.
    if not leaderboard_eligible:
        breakdown.ineligible_reason = "scoring_error" if ctx.has_api_key else "no_api_key"
    return breakdown


def _late_penalty(submission: dict, challenge: dict) -> float:
    time_ms = submission.get("time_taken_ms") or 0
    limit_ms = (challenge.get("time_limit_minutes") or 60) * 60 * 1000
    if time_ms <= 0 or time_ms <= limit_ms:
        return 0.0
    ratio = time_ms / limit_ms
    return 10.0 if ratio <= 1.25 else 20.0 if ratio <= 1.5 else 30.0


def _run(submission_id: str) -> None:
    submission = fetch_one("SELECT * FROM submissions WHERE id=?", (submission_id,))
    if submission is None:
        return
    challenge = fetch_one("SELECT * FROM challenges WHERE id=?", (submission["challenge_id"],))
    if challenge is None:
        return

    ctx = _load_context(submission, challenge)
    breakdown = _assemble(ctx)

    penalty = _late_penalty(submission, challenge)
    overall = max(0.0, round(breakdown.overall - penalty, 1))
    breakdown.late_penalty = penalty
    breakdown.overall = overall
    eligible = 1 if breakdown.leaderboard_eligible else 0

    execute(
        """UPDATE submissions SET status='scored', score=?, score_breakdown=?,
              leaderboard_eligible=?, scoring_version=?, scored_at=datetime('now'),
              updated_at=datetime('now') WHERE id=?""",
        (overall, json.dumps(breakdown.to_json()), eligible, SCORING_VERSION, submission_id),
    )
    _apply_side_effects(submission, overall, eligible)
    logger.info("Scored %s: %.1f (eligible=%s, version=%s)", submission_id, overall, eligible, SCORING_VERSION)


def _apply_side_effects(submission: dict, overall: float, leaderboard_eligible: int) -> None:
    challenge_id = submission["challenge_id"]
    user_id = submission["user_id"]
    submission_id = submission["id"]

    # ── challenge stats (challenge_scoring.py:122-131) ──
    execute(
        """UPDATE challenges SET
              submission_count = (SELECT COUNT(*) FROM submissions WHERE challenge_id = ? AND status = 'scored'),
              avg_score = (SELECT AVG(score) FROM submissions WHERE challenge_id = ? AND status = 'scored'),
              updated_at = datetime('now')
           WHERE id = ?""",
        (challenge_id, challenge_id, challenge_id),
    )

    # ── developer profile + preferred agent + weighted total (challenge_scoring.py:133-165) ──

    # Find most-used agent
    agent_row = fetch_one(
        """SELECT agent_used, COUNT(*) as cnt FROM submissions
           WHERE user_id = ? AND status = 'scored' AND agent_used IS NOT NULL
           GROUP BY agent_used ORDER BY cnt DESC LIMIT 1""",
        (user_id,),
    )
    preferred_agent = agent_row["agent_used"] if agent_row else None

    # Weighted total score: easy=1x, medium=1.5x, hard=2x
    _prof = fetch_one("SELECT streak_days, last_submission_at FROM developer_profiles WHERE user_id = ?", (user_id,))
    new_streak = compute_streak(_prof.get("streak_days") if _prof else 0, _prof.get("last_submission_at") if _prof else None)
    _cur = fetch_one("SELECT direction_rating FROM developer_profiles WHERE user_id = ?", (user_id,))
    _ch = fetch_one("SELECT difficulty, category FROM challenges WHERE id = ?", (challenge_id,))
    new_rating = update_rating(_cur.get("direction_rating") if _cur else 1000, _ch.get("difficulty") if _ch else None, overall)
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
              streak_days = ?,
              direction_rating = ?,
              last_submission_at = datetime('now'),
              updated_at = datetime('now')
           WHERE user_id = ?""",
        (user_id, user_id, preferred_agent, new_streak, new_rating, user_id),
    )

    # ── per-category / per-model mastery ratings (KOD-79) ──
    try:
        _bump_skill_rating(user_id, "category", (_ch.get("category") if _ch else None), (_ch.get("difficulty") if _ch else None), overall)
        _bump_skill_rating(user_id, "model", submission.get("model"), (_ch.get("difficulty") if _ch else None), overall)
    except Exception:
        logger.exception("Skill rating update failed for user %s", user_id)

    # ── recompute global ranks ──
    _recompute_ranks()

    # ── leaderboard upsert (challenge_scoring.py:170-197) ──
    # Only eligible submissions (AI-scored) ever reach a leaderboard; an ineligible
    # submission never creates or overwrites an entry, so any existing eligible entry
    # for this challenge is preserved.
    if leaderboard_eligible:
        existing_entry = fetch_one(
            "SELECT id, score FROM leaderboard_entries WHERE user_id = ? AND challenge_id = ?",
            (user_id, challenge_id),
        )
        if existing_entry is None:
            entry_id = secrets.token_hex(16)
            execute(
                """INSERT INTO leaderboard_entries (id, user_id, challenge_id, submission_id, score, agent_used, model, time_taken_ms, submitted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (entry_id, user_id, challenge_id, submission_id, overall,
                 submission.get("agent_used"), submission.get("model"), submission.get("time_taken_ms")),
            )
        elif overall > existing_entry["score"]:
            execute(
                """UPDATE leaderboard_entries SET
                      submission_id = ?, score = ?, agent_used = ?, model = ?, time_taken_ms = ?,
                      submitted_at = datetime('now')
                   WHERE id = ?""",
                (submission_id, overall, submission.get("agent_used"),
                 submission.get("model"), submission.get("time_taken_ms"), existing_entry["id"]),
            )

    # ── badge evaluation + celebration payload (KOD-79) ──
    new_badges: list[dict] = []
    try:
        from app.services.badge_engine import evaluate_badges
        new_badges = evaluate_badges(user_id, submission_id)
        if new_badges:
            logger.info("Awarded %d badges to user %s: %s",
                        len(new_badges), user_id, [b["slug"] for b in new_badges])
    except Exception:
        logger.exception("Badge evaluation failed for user %s", user_id)

    # Record what just happened so the results page can celebrate it once.
    try:
        best = fetch_one(
            "SELECT MAX(score) AS best FROM submissions WHERE user_id = ? AND challenge_id = ? AND status = 'scored' AND score IS NOT NULL",
            (user_id, challenge_id),
        )
        personal_best = best is None or best["best"] is None or overall >= best["best"]
        celebration = {
            "score": overall,
            "personal_best": bool(personal_best),
            "new_badges": [
                {"slug": b["slug"], "name": b["name"], "icon": b.get("icon"), "description": b.get("description")}
                for b in new_badges
            ],
            "streak": new_streak,
            "streak_milestone": new_streak in (3, 7, 30, 100, 365),
        }
        execute(
            "UPDATE submissions SET celebration = ? WHERE id = ?",
            (json.dumps(celebration), submission_id),
        )
    except Exception:
        logger.exception("Celebration capture failed for user %s", user_id)


def _recompute_ranks() -> None:
    """Recompute global rank based on total_score.

    Only developers with at least one leaderboard-eligible (AI-scored) submission are
    ranked; everyone else has their rank cleared so it never surfaces on a leaderboard
    or share card.
    (Ported verbatim from challenge_scoring.py:626-652)
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
