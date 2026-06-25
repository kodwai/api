from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one

router = APIRouter(tags=["admin-gamification"])


# ---- Tiers ----
class TierCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=40, pattern=r"^[a-z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=60)
    min_rating: int = Field(..., ge=0)
    color: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: int = 0


class TierUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=60)
    min_rating: Optional[int] = Field(None, ge=0)
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    sort_order: Optional[int] = None


def _tier_or_404(key: str) -> dict:
    row = fetch_one("SELECT * FROM tiers WHERE key = ?", (key,))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")
    return row


@router.get("/tiers")
def list_tiers(current_admin: AdminUser) -> list[dict]:
    return fetch_all("SELECT * FROM tiers ORDER BY min_rating ASC")


@router.post("/tiers", status_code=status.HTTP_201_CREATED)
def create_tier(body: TierCreate, current_admin: AdminUser) -> dict:
    if fetch_one("SELECT key FROM tiers WHERE key = ?", (body.key,)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tier key exists")
    execute(
        "INSERT INTO tiers (key,name,min_rating,color,sort_order) VALUES (?,?,?,?,?)",
        (body.key, body.name, body.min_rating, body.color, body.sort_order),
    )
    return _tier_or_404(body.key)


@router.put("/tiers/{key}")
def update_tier(key: str, body: TierUpdate, current_admin: AdminUser) -> dict:
    t = _tier_or_404(key)
    name = body.name if body.name is not None else t["name"]
    min_rating = body.min_rating if body.min_rating is not None else t["min_rating"]
    color = body.color if body.color is not None else t["color"]
    sort_order = body.sort_order if body.sort_order is not None else t["sort_order"]
    execute(
        "UPDATE tiers SET name=?, min_rating=?, color=?, sort_order=? WHERE key=?",
        (name, min_rating, color, sort_order, key),
    )
    return _tier_or_404(key)


@router.delete("/tiers/{key}")
def delete_tier(key: str, current_admin: AdminUser) -> dict:
    _tier_or_404(key)
    execute("DELETE FROM tiers WHERE key = ?", (key,))
    return {"deleted": True, "key": key}


# ---- Quests ----
_SCOPES = {"daily", "weekly"}
_METRICS = {"solved", "high80", "categories"}


class QuestCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    scope: str
    title: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    target: int = Field(..., ge=1)
    reward_xp: int = Field(..., ge=0)
    metric: str
    is_active: bool = True
    sort_order: int = 0


class QuestUpdate(BaseModel):
    scope: Optional[str] = None
    title: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = None
    target: Optional[int] = Field(None, ge=1)
    reward_xp: Optional[int] = Field(None, ge=0)
    metric: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


def _validate_quest_enums(scope, metric):
    if scope is not None and scope not in _SCOPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="scope must be daily|weekly")
    if metric is not None and metric not in _METRICS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="metric must be solved|high80|categories")


def _quest_or_404(key: str) -> dict:
    row = fetch_one("SELECT * FROM quests WHERE key = ?", (key,))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quest not found")
    return row


@router.get("/quests")
def list_quests_admin(current_admin: AdminUser) -> list[dict]:
    return fetch_all("SELECT * FROM quests ORDER BY sort_order, scope, key")


@router.post("/quests", status_code=status.HTTP_201_CREATED)
def create_quest(body: QuestCreate, current_admin: AdminUser) -> dict:
    _validate_quest_enums(body.scope, body.metric)
    if fetch_one("SELECT key FROM quests WHERE key = ?", (body.key,)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Quest key exists")
    execute(
        """INSERT INTO quests (key,scope,title,description,target,reward_xp,metric,is_active,sort_order)
               VALUES (?,?,?,?,?,?,?,?,?)""",
        (body.key, body.scope, body.title, body.description, body.target, body.reward_xp,
         body.metric, int(body.is_active), body.sort_order),
    )
    return _quest_or_404(body.key)


@router.put("/quests/{key}")
def update_quest(key: str, body: QuestUpdate, current_admin: AdminUser) -> dict:
    q = _quest_or_404(key)
    _validate_quest_enums(body.scope, body.metric)
    scope = body.scope if body.scope is not None else q["scope"]
    title = body.title if body.title is not None else q["title"]
    description = body.description if body.description is not None else q["description"]
    target = body.target if body.target is not None else q["target"]
    reward_xp = body.reward_xp if body.reward_xp is not None else q["reward_xp"]
    metric = body.metric if body.metric is not None else q["metric"]
    is_active = int(body.is_active) if body.is_active is not None else q["is_active"]
    sort_order = body.sort_order if body.sort_order is not None else q["sort_order"]
    execute(
        """UPDATE quests SET scope=?, title=?, description=?, target=?, reward_xp=?, metric=?, is_active=?, sort_order=? WHERE key=?""",
        (scope, title, description, target, reward_xp, metric, is_active, sort_order, key),
    )
    return _quest_or_404(key)


@router.delete("/quests/{key}")
def delete_quest(key: str, current_admin: AdminUser) -> dict:
    _quest_or_404(key)
    execute("DELETE FROM quests WHERE key = ?", (key,))
    return {"deleted": True, "key": key}
