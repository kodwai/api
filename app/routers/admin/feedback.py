from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one
from app.schemas.feedback import AdminFeedbackUpdate

router = APIRouter(tags=["admin-feedback"])


# ── Challenge Feedback ──────────────────────────────────────────────


@router.get("/feedback/challenges")
def list_challenge_feedback(
    current_admin: AdminUser,
    challenge_id: Optional[str] = None,
    min_rating: Optional[int] = Query(None, ge=1, le=5),
    max_rating: Optional[int] = Query(None, ge=1, le=5),
    has_comment: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if challenge_id:
        conditions.append("cf.challenge_id = ?")
        params.append(challenge_id)
    if min_rating is not None:
        conditions.append("cf.rating_overall >= ?")
        params.append(min_rating)
    if max_rating is not None:
        conditions.append("cf.rating_overall <= ?")
        params.append(max_rating)
    if has_comment is True:
        conditions.append("cf.comment IS NOT NULL AND cf.comment != ''")
    elif has_comment is False:
        conditions.append("(cf.comment IS NULL OR cf.comment = '')")
    if search:
        conditions.append("(u.name LIKE ? OR u.email LIKE ? OR cf.comment LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT cf.*, u.name AS user_name, u.email AS user_email,
                   c.title AS challenge_title, c.slug AS challenge_slug
            FROM challenge_feedback cf
            JOIN users u ON cf.user_id = u.id
            JOIN challenges c ON cf.challenge_id = c.id
            WHERE {where}
            ORDER BY cf.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    total = fetch_one(
        f"""SELECT COUNT(*) AS count
            FROM challenge_feedback cf
            JOIN users u ON cf.user_id = u.id
            JOIN challenges c ON cf.challenge_id = c.id
            WHERE {where}""",
        tuple(count_params),
    )
    return {"items": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


# ── Platform Feedback ───────────────────────────────────────────────


@router.get("/feedback/platform")
def list_platform_feedback(
    current_admin: AdminUser,
    category: Optional[str] = None,
    fb_status: Optional[str] = Query(None, alias="status"),
    is_flagged: Optional[bool] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if category:
        conditions.append("pf.category = ?")
        params.append(category)
    if fb_status:
        conditions.append("pf.status = ?")
        params.append(fb_status)
    if is_flagged is not None:
        conditions.append("pf.is_flagged = ?")
        params.append(1 if is_flagged else 0)
    if search:
        conditions.append("(u.name LIKE ? OR u.email LIKE ? OR pf.description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT pf.*, u.name AS user_name, u.email AS user_email
            FROM platform_feedback pf
            JOIN users u ON pf.user_id = u.id
            WHERE {where}
            ORDER BY pf.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    total = fetch_one(
        f"""SELECT COUNT(*) AS count
            FROM platform_feedback pf
            JOIN users u ON pf.user_id = u.id
            WHERE {where}""",
        tuple(count_params),
    )
    return {"items": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.put("/feedback/platform/{feedback_id}")
def update_platform_feedback(
    feedback_id: str,
    body: AdminFeedbackUpdate,
    current_admin: AdminUser,
) -> dict:
    """Update status, respond, or flag a platform feedback entry."""
    fb = fetch_one("SELECT * FROM platform_feedback WHERE id = ?", (feedback_id,))
    if fb is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    updates = []
    params: list = []

    if body.status is not None:
        updates.append("status = ?")
        params.append(body.status)
    if body.admin_response is not None:
        updates.append("admin_response = ?")
        params.append(body.admin_response)
        updates.append("admin_responded_by = ?")
        params.append(current_admin["id"])
        updates.append("admin_responded_at = datetime('now')")
    if body.is_flagged is not None:
        updates.append("is_flagged = ?")
        params.append(1 if body.is_flagged else 0)

    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(feedback_id)

    execute(
        f"UPDATE platform_feedback SET {', '.join(updates)} WHERE id = ?",
        tuple(params),
    )

    row = fetch_one(
        """SELECT pf.*, u.name AS user_name, u.email AS user_email
           FROM platform_feedback pf
           JOIN users u ON pf.user_id = u.id
           WHERE pf.id = ?""",
        (feedback_id,),
    )
    return dict(row)


# ── Analytics ───────────────────────────────────────────────────────


@router.get("/feedback/analytics")
def feedback_analytics(current_admin: AdminUser) -> dict:
    """Aggregate feedback statistics."""
    # Per-challenge averages
    challenge_stats = fetch_all(
        """SELECT cf.challenge_id, c.title AS challenge_title, c.slug AS challenge_slug,
                  ROUND(AVG(cf.rating_overall), 2) AS avg_overall,
                  ROUND(AVG(cf.rating_difficulty), 2) AS avg_difficulty,
                  ROUND(AVG(cf.rating_clarity), 2) AS avg_clarity,
                  COUNT(*) AS total_count
           FROM challenge_feedback cf
           JOIN challenges c ON cf.challenge_id = c.id
           GROUP BY cf.challenge_id
           ORDER BY total_count DESC""",
        (),
    )

    # Platform feedback counts by category
    category_counts = fetch_all(
        "SELECT category, COUNT(*) AS count FROM platform_feedback GROUP BY category",
        (),
    )

    # Platform feedback counts by status
    status_counts = fetch_all(
        "SELECT status, COUNT(*) AS count FROM platform_feedback GROUP BY status",
        (),
    )

    # Totals
    cf_total = fetch_one("SELECT COUNT(*) AS count FROM challenge_feedback", ())
    pf_total = fetch_one("SELECT COUNT(*) AS count FROM platform_feedback", ())

    return {
        "challenge_feedback": {
            "total": cf_total["count"] if cf_total else 0,
            "per_challenge": challenge_stats,
        },
        "platform_feedback": {
            "total": pf_total["count"] if pf_total else 0,
            "by_category": {r["category"]: r["count"] for r in category_counts},
            "by_status": {r["status"]: r["count"] for r in status_counts},
        },
    }
