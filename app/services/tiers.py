from __future__ import annotations

from app.core.database import fetch_all

# Ordered ascending by min_rating. Tier derived purely from Direction Rating (ELO).
# Seeded into the `tiers` table via migration 036; kept here as a fallback when the
# table is empty/unavailable.
_DEFAULT_TIERS = [
    {"key": "bronze",      "name": "Bronze",      "min": 0,    "color": "#a1664b"},
    {"key": "silver",      "name": "Silver",      "min": 1000, "color": "#8e9aa3"},
    {"key": "gold",        "name": "Gold",        "min": 1150, "color": "#c8a233"},
    {"key": "platinum",    "name": "Platinum",    "min": 1300, "color": "#3fa6a0"},
    {"key": "diamond",     "name": "Diamond",     "min": 1450, "color": "#4f8cd6"},
    {"key": "master",      "name": "Master",      "min": 1600, "color": "#9b5cd6"},
    {"key": "grandmaster", "name": "Grandmaster", "min": 1800, "color": "#d65c5c"},
]


def load_tiers() -> list[dict]:
    """Load tier definitions from the DB (ascending by min_rating).
    Falls back to the hardcoded defaults if the table is empty/unavailable."""
    rows = fetch_all("SELECT key, name, min_rating AS min, color FROM tiers ORDER BY min_rating ASC")
    return [dict(r) for r in rows] if rows else _DEFAULT_TIERS


def tier_for(rating: int | None, tiers: list[dict] | None = None) -> dict:
    """Return the tier dict for a Direction Rating, plus progress to the next tier.
    Keys: key, name, color, min, next_name (or None), next_at (or None), progress (0..1).
    Pass an explicit `tiers` list (e.g. from load_tiers()) to avoid a DB query per call."""
    if tiers is None:
        tiers = load_tiers()
    r = rating if rating is not None else 1000
    current = tiers[0]
    for t in tiers:
        if r >= t["min"]:
            current = t
        else:
            break
    idx = tiers.index(current)
    nxt = tiers[idx + 1] if idx + 1 < len(tiers) else None
    if nxt:
        span = nxt["min"] - current["min"]
        progress = max(0.0, min(1.0, (r - current["min"]) / span)) if span else 1.0
        next_name, next_at = nxt["name"], nxt["min"]
    else:
        progress, next_name, next_at = 1.0, None, None
    return {
        "key": current["key"], "name": current["name"], "color": current["color"],
        "min": current["min"], "next_name": next_name, "next_at": next_at,
        "progress": round(progress, 3),
    }
