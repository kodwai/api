"""Backfill efficiency_rating + per-submission turns/total_tokens (gamification v2).

Replays every scored submission in chronological order per user, recomputing each
user's efficiency_rating from scratch (start 1000) using the agent-trace economy
(turns vs the expected budget for the challenge difficulty), and writing
submissions.turns / submissions.total_tokens.

Idempotent: it recomputes from scratch every run, so re-running yields the same result.

Run from the repo root:
    python scripts/backfill_efficiency.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure the repo root is on sys.path so `app` is importable.
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.core.database import connect, execute, fetch_all  # noqa: E402
from app.services.scoring.engine import (  # noqa: E402
    efficiency_outcome,
    update_rating,
    _trace_tokens,
    _trace_turns,
)


def main() -> None:
    connect()

    rows = fetch_all(
        """SELECT s.id, s.user_id, s.agent_trace, s.score, c.difficulty AS difficulty
           FROM submissions s
           LEFT JOIN challenges c ON s.challenge_id = c.id
           WHERE s.status = 'scored'
           ORDER BY s.user_id, s.scored_at, s.id""",
    )

    ratings: dict[str, int] = {}
    submissions_updated = 0
    users_seen: set[str] = set()

    for row in rows:
        user_id = row["user_id"]
        users_seen.add(user_id)

        try:
            at = json.loads(row["agent_trace"]) if row.get("agent_trace") else None
        except Exception:
            at = None
        turns = _trace_turns(at)
        tokens = _trace_tokens(at)

        execute(
            "UPDATE submissions SET turns = ?, total_tokens = ? WHERE id = ?",
            (turns, tokens, row["id"]),
        )
        submissions_updated += 1

        cur = ratings.get(user_id, 1000)
        outcome = efficiency_outcome(row.get("score"), row.get("difficulty"), turns)
        ratings[user_id] = update_rating(cur, row.get("difficulty"), outcome)

    for user_id, rating in ratings.items():
        execute(
            "UPDATE developer_profiles SET efficiency_rating = ?, updated_at = datetime('now') WHERE user_id = ?",
            (rating, user_id),
        )

    print("Efficiency backfill complete.")
    print(f"  scored submissions processed: {submissions_updated}")
    print(f"  users updated:                {len(ratings)}")


if __name__ == "__main__":
    main()
