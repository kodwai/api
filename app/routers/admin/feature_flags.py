from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one
from app.schemas.feature_flag import FeatureFlagCreate, FeatureFlagUpdate

router = APIRouter(tags=["admin-feature-flags"])


def _normalize_dt(value: str | None) -> str | None:
    """ISO-8601 / canonical -> canonical 'YYYY-MM-DD HH:MM:SS' (UTC). None/empty -> None. 400 on bad input."""
    if value is None or value == "":
        return None
    try:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        normalized = normalized.replace(" ", "T", 1)
        dt = datetime.fromisoformat(normalized)
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid datetime; expected ISO-8601")


def _get_or_404(key: str) -> dict:
    flag = fetch_one("SELECT * FROM feature_flags WHERE key = ?", (key,))
    if flag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flag not found")
    return flag


@router.get("/feature-flags")
def admin_list_flags(current_admin: AdminUser) -> list[dict]:
    return fetch_all("SELECT * FROM feature_flags ORDER BY key")


@router.post("/feature-flags", status_code=status.HTTP_201_CREATED)
def admin_create_flag(body: FeatureFlagCreate, current_admin: AdminUser) -> dict:
    if fetch_one("SELECT key FROM feature_flags WHERE key = ?", (body.key,)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Flag key already exists")
    execute(
        """INSERT INTO feature_flags (key, name, description, enabled, starts_at, ends_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        (body.key, body.name, body.description, int(body.enabled),
         _normalize_dt(body.starts_at), _normalize_dt(body.ends_at)),
    )
    return _get_or_404(body.key)


@router.put("/feature-flags/{key}")
def admin_update_flag(key: str, body: FeatureFlagUpdate, current_admin: AdminUser) -> dict:
    # Clear-vs-unchanged semantics: a field sent as "" clears (-> NULL); omitted/None leaves it unchanged.
    flag = _get_or_404(key)
    name = body.name if body.name is not None else flag["name"]
    description = body.description if body.description is not None else flag["description"]
    enabled = int(body.enabled) if body.enabled is not None else flag["enabled"]
    starts_at = _normalize_dt(body.starts_at) if body.starts_at is not None else flag["starts_at"]
    ends_at = _normalize_dt(body.ends_at) if body.ends_at is not None else flag["ends_at"]
    execute(
        """UPDATE feature_flags SET name = ?, description = ?, enabled = ?,
               starts_at = ?, ends_at = ?, updated_at = datetime('now') WHERE key = ?""",
        (name, description, enabled, starts_at, ends_at, key),
    )
    return _get_or_404(key)
