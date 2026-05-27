from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.core.database import fetch_all, fetch_one

router = APIRouter(prefix="/events", tags=["events"])


def _parse_canonical(value: str) -> datetime:
    """Parse a stored datetime string (canonical 'YYYY-MM-DD HH:MM:SS' or any
    ISO-8601 variant) into a timezone-aware UTC datetime.  Offset-naive values
    are treated as UTC.
    """
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    # Replace space separator with T for fromisoformat compatibility
    normalized = normalized.replace(" ", "T", 1)
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _compute_status(starts_at: str, ends_at: str) -> str:
    """Return 'upcoming', 'active', or 'ended' relative to now (UTC).

    Compares using parsed datetime objects so any stored format (canonical
    space-separated OR ISO-8601 with T/offset) produces a correct result.
    """
    now = datetime.now(timezone.utc)
    starts = _parse_canonical(starts_at)
    ends   = _parse_canonical(ends_at)
    if now < starts:
        return "upcoming"
    if now <= ends:
        return "active"
    return "ended"


def _enrich(row: dict) -> dict:
    row["status"] = _compute_status(row["starts_at"], row["ends_at"])
    row["is_finalized"] = bool(row.get("is_finalized", 0))
    return row


def _lookup_event(id_or_slug: str) -> dict:
    """Fetch event by id or slug; raise 404 if not found."""
    row = fetch_one(
        "SELECT * FROM events WHERE id = ? OR slug = ? LIMIT 1",
        (id_or_slug, id_or_slug),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return _enrich(row)


@router.get("")
def list_events() -> list[dict]:
    """List all events ordered by starts_at descending, with derived status."""
    rows = fetch_all("SELECT * FROM events ORDER BY starts_at DESC")
    return [_enrich(r) for r in rows]


@router.get("/{id_or_slug}")
def get_event(id_or_slug: str) -> dict:
    """Single event by id or slug."""
    return _lookup_event(id_or_slug)


@router.get("/{id_or_slug}/leaderboard")
def event_leaderboard(id_or_slug: str) -> list[dict]:
    """Ranked developers for an event.

    Only eligible (status='scored', leaderboard_eligible=1) submissions whose
    scored_at falls within [event.starts_at, event.ends_at] are included.
    Best score per user, ranked desc; earliest scored_at breaks ties.
    """
    event = _lookup_event(id_or_slug)

    # Step 1: best (max) score per user within the window.
    # Step 2: for agent_used, join back to pick the row that achieved the best score
    #         (earliest scored_at if tied), without using aggregate in a correlated subquery.
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
                 AND datetime(s.scored_at) >= datetime(?)
                 AND datetime(s.scored_at) <= datetime(?)
               GROUP BY s.user_id
           ) best
           JOIN users u ON best.user_id = u.id
           -- Re-join to retrieve the agent_used from the winning submission row
           LEFT JOIN submissions winning
               ON winning.user_id = best.user_id
              AND winning.score = best.top_score
              AND winning.status = 'scored'
              AND winning.leaderboard_eligible = 1
              AND datetime(winning.scored_at) >= datetime(?)
              AND datetime(winning.scored_at) <= datetime(?)
              AND winning.scored_at = (
                  SELECT MIN(s3.scored_at)
                  FROM submissions s3
                  WHERE s3.user_id = best.user_id
                    AND s3.score = best.top_score
                    AND s3.status = 'scored'
                    AND s3.leaderboard_eligible = 1
                    AND datetime(s3.scored_at) >= datetime(?)
                    AND datetime(s3.scored_at) <= datetime(?)
              )
           ORDER BY best.top_score DESC, best.earliest_scored_at ASC
           LIMIT 100""",
        (
            event["starts_at"], event["ends_at"],
            event["starts_at"], event["ends_at"],
            event["starts_at"], event["ends_at"],
        ),
    )

    return rows
