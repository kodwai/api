from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.database import fetch_all
from app.services.feature_flags import is_flag_active

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


@router.get("")
def list_feature_flags() -> list[dict]:
    """Public: every flag with its computed `active` state (enabled + within any window)."""
    now = datetime.now(timezone.utc)
    rows = fetch_all("SELECT * FROM feature_flags ORDER BY key")
    out = []
    for r in rows:
        out.append({
            "key": r["key"],
            "name": r["name"],
            "description": r["description"],
            "active": is_flag_active(r, now),
        })
    return out
