from __future__ import annotations
from app.core.database import fetch_all, fetch_one

_DIFF_MULT = {"easy": 1.0, "medium": 1.5, "hard": 2.0}

def submission_xp(score: float | None, difficulty: str | None) -> int:
    s = max(0.0, min(100.0, score or 0.0))
    return round(s * _DIFF_MULT.get((difficulty or "").lower(), 1.0))

def level_for(xp: int | None) -> dict:
    """Cumulative thresholds: level n requires 50*n*(n-1) XP (L1=0, L2=100, L3=300, L4=600, L5=1000...)."""
    xp = max(0, int(xp or 0))
    n = 1
    while 50 * (n + 1) * n <= xp:
        n += 1
    floor = 50 * n * (n - 1)
    nxt = 50 * (n + 1) * n
    span = nxt - floor
    return {"level": n, "xp": xp, "level_floor": floor, "next_level_xp": nxt,
            "progress": round((xp - floor) / span, 3) if span else 1.0}

def compute_total_xp(user_id: str) -> int:
    rows = fetch_all(
        """SELECT s.score, c.difficulty FROM submissions s JOIN challenges c ON c.id=s.challenge_id
           WHERE s.user_id=? AND s.status='scored' AND s.score IS NOT NULL""", (user_id,))
    base = sum(submission_xp(r["score"], r["difficulty"]) for r in rows)
    q = fetch_one("SELECT COALESCE(SUM(xp),0) AS x FROM quest_claims WHERE user_id=?", (user_id,))
    return base + int((q or {}).get("x") or 0)
