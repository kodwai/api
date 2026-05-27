from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.core.database import fetch_all, fetch_one

router = APIRouter(prefix="/events", tags=["events"])


def _compute_status(starts_at: str, ends_at: str) -> str:
    """Return 'upcoming', 'active', or 'ended' relative to now (UTC)."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    if now < starts_at:
        return "upcoming"
    if now <= ends_at:
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
                 AND s.scored_at >= ?
                 AND s.scored_at <= ?
               GROUP BY s.user_id
           ) best
           JOIN users u ON best.user_id = u.id
           -- Re-join to retrieve the agent_used from the winning submission row
           LEFT JOIN submissions winning
               ON winning.user_id = best.user_id
              AND winning.score = best.top_score
              AND winning.status = 'scored'
              AND winning.leaderboard_eligible = 1
              AND winning.scored_at >= ?
              AND winning.scored_at <= ?
              AND winning.scored_at = (
                  SELECT MIN(s3.scored_at)
                  FROM submissions s3
                  WHERE s3.user_id = best.user_id
                    AND s3.score = best.top_score
                    AND s3.status = 'scored'
                    AND s3.leaderboard_eligible = 1
                    AND s3.scored_at >= ?
                    AND s3.scored_at <= ?
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
