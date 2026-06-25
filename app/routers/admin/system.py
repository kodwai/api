from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Query

from app.core.admin_deps import AdminUser
from app.core.database import fetch_all, fetch_one

router = APIRouter(tags=["admin-system"])


@router.get("/system/health")
def system_health(current_admin: AdminUser) -> dict:
    """System health check."""
    # DB connection test
    db_ok = False
    try:
        result = fetch_one("SELECT 1 as ok")
        db_ok = result is not None
    except Exception:
        pass

    # Last migration
    last_migration = fetch_one("SELECT name, applied_at FROM _migrations ORDER BY applied_at DESC LIMIT 1")

    # Table counts
    tables = {}
    for table in ["users", "organizations", "challenges", "submissions", "sessions", "badges", "developer_badges", "leaderboard_entries", "admin_audit_log"]:
        try:
            row = fetch_one(f"SELECT COUNT(*) as count FROM {table}")
            tables[table] = row["count"] if row else 0
        except Exception:
            tables[table] = -1

    return {
        "status": "ok" if db_ok else "error",
        "database": "connected" if db_ok else "disconnected",
        "last_migration": last_migration,
        "table_counts": tables,
    }


@router.get("/audit-log")
def list_audit_log(
    current_admin: AdminUser,
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    admin_user_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if action:
        conditions.append("a.action = ?")
        params.append(action)
    if entity_type:
        conditions.append("a.entity_type = ?")
        params.append(entity_type)
    if admin_user_id:
        conditions.append("a.admin_user_id = ?")
        params.append(admin_user_id)

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT a.*, u.name as admin_name, u.email as admin_email
            FROM admin_audit_log a
            JOIN users u ON a.admin_user_id = u.id
            WHERE {where}
            ORDER BY a.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    for r in rows:
        r["details"] = json.loads(r["details"]) if r.get("details") else {}

    total = fetch_one(f"SELECT COUNT(*) as count FROM admin_audit_log a WHERE {where}", tuple(count_params))
    return {"entries": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}
