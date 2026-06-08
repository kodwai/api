from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, status

from app.core.database import fetch_all, fetch_one
from app.core.deps import CurrentUser
from app.routers.challenges import _row_to_list_response

router = APIRouter(prefix="/sprint", tags=["sprint"])


def week_window(now: datetime) -> tuple[str, str, str]:
    """ISO-week window for `now` (UTC). Returns (week_key, starts_at, ends_at)
    as canonical SQLite strings 'YYYY-MM-DD HH:MM:SS'. Window is Monday 00:00:00
    (inclusive) to the next Monday 00:00:00 (exclusive)."""
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = midnight - timedelta(days=now.weekday())
    next_monday = monday + timedelta(days=7)
    week_key = now.strftime("%G-W%V")
    fmt = "%Y-%m-%d %H:%M:%S"
    return week_key, monday.strftime(fmt), next_monday.strftime(fmt)


def sprint_index(week_key: str, count: int) -> int:
    """Deterministic index into `count` items for an ISO week key.
    Salted with 'sprint:' so it does not trivially mirror the daily pick."""
    if count <= 0:
        return 0
    return int(hashlib.sha256(("sprint:" + week_key).encode("utf-8")).hexdigest(), 16) % count


@router.get("/current")
def current_sprint(current_user: CurrentUser) -> dict:
    """This week's deterministic sprint challenge + live leaderboard + the
    caller's standing. Window is the current ISO week (UTC)."""
    challenges = fetch_all("SELECT * FROM challenges WHERE is_public = 1 ORDER BY id")
    if not challenges:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No challenges available")

    week_key, starts_at, ends_at = week_window(datetime.now(timezone.utc))
    chosen = challenges[sprint_index(week_key, len(challenges))]

    rows = fetch_all(
        """SELECT
               ROW_NUMBER() OVER (ORDER BY best.top_score DESC, best.earliest_scored_at ASC) AS rank,
               best.user_id,
               u.name,
               u.username,
               best.top_score AS score,
               winning.agent_used,
               best.earliest_scored_at AS scored_at
           FROM (
               SELECT
                   s.user_id,
                   MAX(s.score) AS top_score,
                   MIN(s.scored_at) AS earliest_scored_at
               FROM submissions s
               WHERE s.status = 'scored'
                 AND s.leaderboard_eligible = 1
                 AND s.challenge_id = ?
                 AND datetime(s.scored_at) >= datetime(?)
                 AND datetime(s.scored_at) < datetime(?)
               GROUP BY s.user_id
           ) best
           JOIN users u ON best.user_id = u.id
           LEFT JOIN submissions winning
               ON winning.user_id = best.user_id
              AND winning.score = best.top_score
              AND winning.challenge_id = ?
              AND winning.status = 'scored'
              AND winning.leaderboard_eligible = 1
              AND datetime(winning.scored_at) >= datetime(?)
              AND datetime(winning.scored_at) < datetime(?)
              AND winning.scored_at = (
                  SELECT MIN(s3.scored_at)
                  FROM submissions s3
                  WHERE s3.user_id = best.user_id
                    AND s3.score = best.top_score
                    AND s3.challenge_id = ?
                    AND s3.status = 'scored'
                    AND s3.leaderboard_eligible = 1
                    AND datetime(s3.scored_at) >= datetime(?)
                    AND datetime(s3.scored_at) < datetime(?)
              )
           ORDER BY best.top_score DESC, best.earliest_scored_at ASC
           LIMIT 100""",
        (
            chosen["id"], starts_at, ends_at,
            chosen["id"], starts_at, ends_at,
            chosen["id"], starts_at, ends_at,
        ),
    )

    me = {"rank": None, "best_score": None, "participated": False}
    for r in rows:
        if r["user_id"] == current_user["id"]:
            me = {"rank": r["rank"], "best_score": r["score"], "participated": True}
            break

    listed = _row_to_list_response(chosen)
    challenge = listed.model_dump() if hasattr(listed, "model_dump") else listed
    return {
        "week_key": week_key,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "challenge": challenge,
        "leaderboard": rows,
        "me": me,
    }
