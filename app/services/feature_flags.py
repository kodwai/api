from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status

from app.core.database import fetch_one


def _parse(value: str) -> datetime:
    """Parse a stored datetime ('YYYY-MM-DD HH:MM:SS' canonical or ISO-8601) as aware UTC."""
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    normalized = normalized.replace(" ", "T", 1)
    dt = datetime.fromisoformat(normalized)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def is_flag_active(flag: dict | None, now: datetime) -> bool:
    """A flag is active when it exists, is enabled, and (if a window is set) now is inside it.
    Fail-closed: a missing flag is inactive."""
    if not flag or not flag.get("enabled"):
        return False
    starts_at = flag.get("starts_at")
    ends_at = flag.get("ends_at")
    if starts_at and now < _parse(starts_at):
        return False
    if ends_at and now > _parse(ends_at):
        return False
    return True


def flag_active_by_key(key: str) -> bool:
    flag = fetch_one("SELECT * FROM feature_flags WHERE key = ?", (key,))
    return is_flag_active(flag, datetime.now(timezone.utc))


def require_flag(key: str):
    """FastAPI route dependency: 404 when the flag is inactive."""
    def _dep() -> None:
        if not flag_active_by_key(key):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feature not available")
    return Depends(_dep)
