"""Background task that expires timed-out sessions every 60 seconds."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from app.core.database import fetch_all, execute

logger = logging.getLogger(__name__)


def _expire_sessions() -> int:
    """Find active sessions that have exceeded their time limit and mark them as expired.

    Returns the number of sessions expired.
    """
    now = datetime.now(timezone.utc)

    # Get all active sessions with their project time limits
    active_sessions = fetch_all(
        """SELECT s.id, s.started_at, p.time_limit_minutes
           FROM sessions s
           JOIN projects p ON s.project_id = p.id
           WHERE s.status = 'active' AND s.started_at IS NOT NULL""",
        (),
    )

    expired_count = 0
    for session in active_sessions:
        started_at = datetime.fromisoformat(session["started_at"].replace("Z", "+00:00"))
        time_limit = session["time_limit_minutes"] or 60
        elapsed_minutes = (now - started_at).total_seconds() / 60

        if elapsed_minutes > time_limit:
            logger.info(
                "Expiring session %s — elapsed %.1f min, limit %d min",
                session["id"], elapsed_minutes, time_limit,
            )
            execute(
                """UPDATE sessions
                   SET status = 'expired', ended_at = ?, end_reason = 'timer_expired', updated_at = ?
                   WHERE id = ? AND status = 'active'""",
                (now.isoformat(), now.isoformat(), session["id"]),
            )

            # Trigger AI scoring for expired sessions
            try:
                import threading as _t
                from app.services.scoring_service import trigger_ai_scoring

                def _score(sid=session["id"]):
                    try:
                        trigger_ai_scoring(sid)
                    except Exception:
                        logger.exception("AI scoring failed for expired session %s", sid)

                _t.Thread(target=_score, daemon=True).start()
            except Exception:
                logger.exception("Failed to trigger scoring for expired session %s", session["id"])

            expired_count += 1

    return expired_count


def _cleanup_loop() -> None:
    """Run the session cleanup every 60 seconds."""
    while True:
        try:
            count = _expire_sessions()
            if count > 0:
                logger.info("Session cleanup: expired %d session(s)", count)
        except Exception:
            logger.exception("Session cleanup error")
        time.sleep(60)


def start_session_cleanup() -> None:
    """Start the background session cleanup thread."""
    thread = threading.Thread(target=_cleanup_loop, daemon=True, name="session-cleanup")
    thread.start()
    logger.info("Session cleanup background task started (every 60s)")
