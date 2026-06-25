"""Submission lifecycle operations beyond create/score — currently deletion.

Deleting a submission (a developer stopping an in-progress challenge, or removing
a finished one) must reconcile every piece of derived state. FK enforcement is
off at runtime, so child references are cleaned up explicitly rather than relying
on ON DELETE CASCADE / SET NULL.
"""
from __future__ import annotations

import logging
import secrets

from app.core.database import execute, fetch_one
from app.services.scoring.engine import _recompute_ranks

logger = logging.getLogger(__name__)


def delete_submission(submission: dict) -> None:
    """Delete a submission and reconcile derived state.

    Derived stats (leaderboard, challenge averages, profile totals, ranks) only
    change when the deleted submission was scored, so the recompute is skipped for
    in-progress / errored rows. A spent free credit is intentionally NOT refunded
    (the free_submissions_used counter is monotonic), so deleting cannot be used to
    farm free platform-scored submissions.
    """
    submission_id = submission["id"]
    user_id = submission["user_id"]
    challenge_id = submission["challenge_id"]
    was_scored = submission["status"] == "scored"

    # Unlink child references so nothing dangles (FK actions don't fire at runtime).
    # Badges stay earned; feedback stays, just detached from the deleted submission.
    execute("UPDATE developer_badges SET submission_id = NULL WHERE submission_id = ?", (submission_id,))
    execute("UPDATE challenge_feedback SET submission_id = NULL WHERE submission_id = ?", (submission_id,))

    execute("DELETE FROM submissions WHERE id = ?", (submission_id,))

    if not was_scored:
        return

    _rebuild_leaderboard_entry(user_id, challenge_id)
    _recompute_challenge_stats(challenge_id)
    _recompute_profile_stats(user_id)
    _recompute_ranks()


def _rebuild_leaderboard_entry(user_id: str, challenge_id: str) -> None:
    """Reconcile the (user, challenge) leaderboard entry from scratch.

    Points it at the best remaining eligible submission, or removes it if none
    remain. Idempotent regardless of what the entry previously referenced.
    """
    best = fetch_one(
        """SELECT id, score, agent_used, time_taken_ms, submitted_at
           FROM submissions
           WHERE user_id = ? AND challenge_id = ? AND status = 'scored' AND leaderboard_eligible = 1
           ORDER BY score DESC LIMIT 1""",
        (user_id, challenge_id),
    )
    existing = fetch_one(
        "SELECT id FROM leaderboard_entries WHERE user_id = ? AND challenge_id = ?",
        (user_id, challenge_id),
    )

    if best is None:
        if existing:
            execute("DELETE FROM leaderboard_entries WHERE id = ?", (existing["id"],))
        return

    if existing:
        execute(
            """UPDATE leaderboard_entries SET submission_id = ?, score = ?, agent_used = ?,
                  time_taken_ms = ?, submitted_at = COALESCE(?, datetime('now')) WHERE id = ?""",
            (best["id"], best["score"], best["agent_used"], best["time_taken_ms"],
             best["submitted_at"], existing["id"]),
        )
    else:
        execute(
            """INSERT INTO leaderboard_entries
                  (id, user_id, challenge_id, submission_id, score, agent_used, time_taken_ms, submitted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))""",
            (secrets.token_hex(16), user_id, challenge_id, best["id"], best["score"],
             best["agent_used"], best["time_taken_ms"], best["submitted_at"]),
        )


def _recompute_challenge_stats(challenge_id: str) -> None:
    execute(
        """UPDATE challenges SET
              submission_count = (SELECT COUNT(*) FROM submissions WHERE challenge_id = ? AND status = 'scored'),
              avg_score = (SELECT AVG(score) FROM submissions WHERE challenge_id = ? AND status = 'scored'),
              updated_at = datetime('now')
           WHERE id = ?""",
        (challenge_id, challenge_id, challenge_id),
    )


def _recompute_profile_stats(user_id: str) -> None:
    """Recompute a developer's derived totals after a scored submission is removed.

    Mirrors the post-scoring recompute in scoring.engine, but derives
    last_submission_at from the remaining rows (the scoring path can use 'now'
    because a submission just landed; a deletion cannot).
    """
    execute(
        """UPDATE developer_profiles SET
              challenges_completed = (SELECT COUNT(DISTINCT challenge_id) FROM submissions WHERE user_id = ? AND status = 'scored'),
              total_score = COALESCE(
                (SELECT SUM(best.weighted_score) / SUM(best.weight) FROM (
                  SELECT s.challenge_id,
                         CASE c.difficulty WHEN 'easy' THEN 1.0 WHEN 'medium' THEN 1.5 WHEN 'hard' THEN 2.0 ELSE 1.0 END as weight,
                         MAX(s.score) * CASE c.difficulty WHEN 'easy' THEN 1.0 WHEN 'medium' THEN 1.5 WHEN 'hard' THEN 2.0 ELSE 1.0 END as weighted_score
                  FROM submissions s
                  JOIN challenges c ON s.challenge_id = c.id
                  WHERE s.user_id = ? AND s.status = 'scored' AND s.leaderboard_eligible = 1
                  GROUP BY s.challenge_id
                ) best), 0),
              preferred_agent = (
                SELECT agent_used FROM submissions
                WHERE user_id = ? AND status = 'scored' AND agent_used IS NOT NULL
                GROUP BY agent_used ORDER BY COUNT(*) DESC LIMIT 1),
              last_submission_at = (SELECT MAX(submitted_at) FROM submissions WHERE user_id = ? AND status = 'scored'),
              updated_at = datetime('now')
           WHERE user_id = ?""",
        (user_id, user_id, user_id, user_id, user_id),
    )
