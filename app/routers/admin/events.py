from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, status

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one
from app.schemas.event import EventCreate

router = APIRouter(tags=["admin-events"])


def _leaderboard_for_event(event_id: str) -> list[dict]:
    """Return the event leaderboard rows (same query as public endpoint)."""
    event = fetch_one("SELECT starts_at, ends_at FROM events WHERE id = ?", (event_id,))
    if event is None:
        return []

    rows = fetch_all(
        """SELECT
               best.user_id,
               best.top_score AS score,
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
           ORDER BY best.top_score DESC, best.earliest_scored_at ASC
           LIMIT 100""",
        (event["starts_at"], event["ends_at"]),
    )
    return rows


@router.post("/events")
def create_event(body: EventCreate, current_admin: AdminUser) -> dict:
    """Create a new time-boxed event. ends_at must be after starts_at."""
    if body.ends_at <= body.starts_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ends_at must be after starts_at",
        )

    existing = fetch_one("SELECT id FROM events WHERE slug = ?", (body.slug,))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An event with this slug already exists",
        )

    event_id = secrets.token_hex(16)
    execute(
        """INSERT INTO events (id, title, slug, description, starts_at, ends_at, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (event_id, body.title, body.slug, body.description, body.starts_at, body.ends_at, current_admin["id"]),
    )
    return fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))


@router.post("/events/{event_id}/finalize")
def finalize_event(event_id: str, current_admin: AdminUser) -> dict:
    """Compute top-3 from the event leaderboard and record them as winners.

    Idempotency: if the event is already finalized this is a no-op — the
    existing winners and badge grants are returned unchanged. To re-finalize,
    the caller must first manually clear is_finalized via the DB; this keeps
    the endpoint safe to call multiple times without data loss.
    """
    event = fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    if event["is_finalized"]:
        # Return existing winners — idempotent
        winners = fetch_all(
            """SELECT ew.*, u.name, u.username
               FROM event_winners ew
               JOIN users u ON ew.user_id = u.id
               WHERE ew.event_id = ?
               ORDER BY ew.rank""",
            (event_id,),
        )
        return {"event_id": event_id, "is_finalized": True, "winners": winners}

    # Compute top-3
    leaderboard = _leaderboard_for_event(event_id)
    top3 = leaderboard[:3]

    # Fetch the event-top-3 badge id (seeded in migration)
    badge = fetch_one("SELECT id FROM badges WHERE slug = 'event-top-3'")

    for rank_idx, entry in enumerate(top3, start=1):
        winner_id = secrets.token_hex(16)
        execute(
            """INSERT OR IGNORE INTO event_winners (id, event_id, user_id, rank, score)
               VALUES (?, ?, ?, ?, ?)""",
            (winner_id, event_id, entry["user_id"], rank_idx, entry["score"]),
        )
        if badge:
            dev_badge_id = secrets.token_hex(16)
            execute(
                """INSERT OR IGNORE INTO developer_badges (id, user_id, badge_id)
                   VALUES (?, ?, ?)""",
                (dev_badge_id, entry["user_id"], badge["id"]),
            )

    execute("UPDATE events SET is_finalized = 1 WHERE id = ?", (event_id,))

    winners = fetch_all(
        """SELECT ew.*, u.name, u.username
           FROM event_winners ew
           JOIN users u ON ew.user_id = u.id
           WHERE ew.event_id = ?
           ORDER BY ew.rank""",
        (event_id,),
    )
    return {"event_id": event_id, "is_finalized": True, "winners": winners}
