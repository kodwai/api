from __future__ import annotations

# Ordered ascending by min_rating. Tier derived purely from Direction Rating (ELO).
TIERS = [
    {"key": "bronze",      "name": "Bronze",      "min": 0,    "color": "#a1664b"},
    {"key": "silver",      "name": "Silver",      "min": 1000, "color": "#8e9aa3"},
    {"key": "gold",        "name": "Gold",        "min": 1150, "color": "#c8a233"},
    {"key": "platinum",    "name": "Platinum",    "min": 1300, "color": "#3fa6a0"},
    {"key": "diamond",     "name": "Diamond",     "min": 1450, "color": "#4f8cd6"},
    {"key": "master",      "name": "Master",      "min": 1600, "color": "#9b5cd6"},
    {"key": "grandmaster", "name": "Grandmaster", "min": 1800, "color": "#d65c5c"},
]


def tier_for(rating: int | None) -> dict:
    """Return the tier dict for a Direction Rating, plus progress to the next tier.
    Keys: key, name, color, min, next_name (or None), next_at (or None), progress (0..1)."""
    r = rating if rating is not None else 1000
    current = TIERS[0]
    for t in TIERS:
        if r >= t["min"]:
            current = t
        else:
            break
    idx = TIERS.index(current)
    nxt = TIERS[idx + 1] if idx + 1 < len(TIERS) else None
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
