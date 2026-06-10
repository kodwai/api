from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status
from app.core.database import execute, fetch_one
from app.core.deps import CurrentUser
from app.services.quests import QUESTS, quest_progress, period_key, get_quest

router = APIRouter(prefix="/quests", tags=["quests"])

@router.get("")
def list_quests(current_user: CurrentUser) -> list[dict]:
    uid = current_user["id"]; now = datetime.now(timezone.utc); out = []
    for q in QUESTS:
        pk = period_key(q, now)
        cur = quest_progress(uid, q, now)
        claimed = fetch_one("SELECT 1 FROM quest_claims WHERE user_id=? AND quest_key=? AND period_key=?", (uid, q["key"], pk)) is not None
        out.append({"key": q["key"], "scope": q["scope"], "title": q["title"], "description": q["description"],
                    "target": q["target"], "current": min(cur, q["target"]), "reward_xp": q["reward_xp"],
                    "completed": cur >= q["target"], "claimed": claimed})
    return out

@router.post("/{key}/claim")
def claim_quest(key: str, current_user: CurrentUser) -> dict:
    q = get_quest(key)
    if not q:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown quest")
    uid = current_user["id"]; now = datetime.now(timezone.utc); pk = period_key(q, now)
    if quest_progress(uid, q, now) < q["target"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Quest not complete")
    if fetch_one("SELECT 1 FROM quest_claims WHERE user_id=? AND quest_key=? AND period_key=?", (uid, key, pk)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already claimed")
    execute("INSERT INTO quest_claims (user_id, quest_key, period_key, xp) VALUES (?, ?, ?, ?)", (uid, key, pk, q["reward_xp"]))
    return {"claimed": True, "key": key, "reward_xp": q["reward_xp"]}
