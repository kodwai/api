from __future__ import annotations

import json
import secrets
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status

from app.core.admin_deps import AdminUser
from app.core.database import execute, fetch_all, fetch_one
from app.schemas.blog import (
    BlogCategoryCreate,
    BlogCategoryUpdate,
    BlogPostCreate,
    BlogPostUpdate,
    BlogTagCreate,
    BlogTagUpdate,
)

router = APIRouter(tags=["admin-blog"])


# ─── Helpers ──────────────────────────────────────────────────────────

def _audit(admin_id: str, action: str, entity_type: str, entity_id: str, details: dict) -> None:
    audit_id = secrets.token_hex(16)
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (audit_id, admin_id, action, entity_type, entity_id, json.dumps(details)),
    )


def _get_post_tags(post_id: str) -> list[dict]:
    return fetch_all(
        """SELECT t.id, t.name, t.slug FROM blog_tags t
           JOIN blog_post_tags pt ON pt.tag_id = t.id
           WHERE pt.post_id = ?""",
        (post_id,),
    )


def _get_post_category(category_id: str | None) -> dict | None:
    if not category_id:
        return None
    return fetch_one("SELECT id, name, slug FROM blog_categories WHERE id = ?", (category_id,))


def _set_post_tags(post_id: str, tag_ids: list[str]) -> None:
    execute("DELETE FROM blog_post_tags WHERE post_id = ?", (post_id,))
    for tag_id in tag_ids:
        tag = fetch_one("SELECT id FROM blog_tags WHERE id = ?", (tag_id,))
        if tag:
            execute("INSERT INTO blog_post_tags (post_id, tag_id) VALUES (?, ?)", (post_id, tag_id))


def _enrich_post(row: dict) -> dict:
    row["category"] = _get_post_category(row.get("category_id"))
    row["tags"] = _get_post_tags(row["id"])
    return row


# ─── Categories ───────────────────────────────────────────────────────

@router.get("/blog/categories")
def list_categories(current_admin: AdminUser) -> list[dict]:
    rows = fetch_all(
        """SELECT c.*, COUNT(p.id) as post_count
           FROM blog_categories c
           LEFT JOIN blog_posts p ON p.category_id = c.id
           GROUP BY c.id
           ORDER BY c.sort_order, c.name""",
        (),
    )
    return rows


@router.post("/blog/categories", status_code=201)
def create_category(body: BlogCategoryCreate, current_admin: AdminUser) -> dict:
    existing = fetch_one("SELECT id FROM blog_categories WHERE slug = ?", (body.slug,))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category slug already exists")

    cat_id = secrets.token_hex(16)
    execute(
        "INSERT INTO blog_categories (id, name, slug, description, sort_order) VALUES (?, ?, ?, ?, ?)",
        (cat_id, body.name, body.slug, body.description, body.sort_order),
    )
    _audit(current_admin["id"], "create_blog_category", "blog_category", cat_id, {"name": body.name})
    return fetch_one("SELECT * FROM blog_categories WHERE id = ?", (cat_id,))


@router.put("/blog/categories/{category_id}")
def update_category(category_id: str, body: BlogCategoryUpdate, current_admin: AdminUser) -> dict:
    cat = fetch_one("SELECT id FROM blog_categories WHERE id = ?", (category_id,))
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    updates: list[str] = []
    params: list = []
    for field, value in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field} = ?")
        params.append(value)

    if updates:
        params.append(category_id)
        execute(f"UPDATE blog_categories SET {', '.join(updates)} WHERE id = ?", tuple(params))
        _audit(current_admin["id"], "update_blog_category", "blog_category", category_id, {"fields": list(body.model_dump(exclude_unset=True).keys())})

    return fetch_one("SELECT * FROM blog_categories WHERE id = ?", (category_id,))


@router.delete("/blog/categories/{category_id}")
def delete_category(category_id: str, current_admin: AdminUser) -> dict:
    cat = fetch_one("SELECT id, name FROM blog_categories WHERE id = ?", (category_id,))
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    execute("DELETE FROM blog_categories WHERE id = ?", (category_id,))
    _audit(current_admin["id"], "delete_blog_category", "blog_category", category_id, {"name": cat["name"]})
    return {"deleted": True}


# ─── Tags ─────────────────────────────────────────────────────────────

@router.get("/blog/tags")
def list_tags(current_admin: AdminUser) -> list[dict]:
    rows = fetch_all(
        """SELECT t.*, COUNT(pt.post_id) as post_count
           FROM blog_tags t
           LEFT JOIN blog_post_tags pt ON pt.tag_id = t.id
           GROUP BY t.id
           ORDER BY t.name""",
        (),
    )
    return rows


@router.post("/blog/tags", status_code=201)
def create_tag(body: BlogTagCreate, current_admin: AdminUser) -> dict:
    existing = fetch_one("SELECT id FROM blog_tags WHERE slug = ?", (body.slug,))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tag slug already exists")

    tag_id = secrets.token_hex(16)
    execute(
        "INSERT INTO blog_tags (id, name, slug) VALUES (?, ?, ?)",
        (tag_id, body.name, body.slug),
    )
    _audit(current_admin["id"], "create_blog_tag", "blog_tag", tag_id, {"name": body.name})
    return fetch_one("SELECT * FROM blog_tags WHERE id = ?", (tag_id,))


@router.put("/blog/tags/{tag_id}")
def update_tag(tag_id: str, body: BlogTagUpdate, current_admin: AdminUser) -> dict:
    tag = fetch_one("SELECT id FROM blog_tags WHERE id = ?", (tag_id,))
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")

    updates: list[str] = []
    params: list = []
    for field, value in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field} = ?")
        params.append(value)

    if updates:
        params.append(tag_id)
        execute(f"UPDATE blog_tags SET {', '.join(updates)} WHERE id = ?", tuple(params))
        _audit(current_admin["id"], "update_blog_tag", "blog_tag", tag_id, {"fields": list(body.model_dump(exclude_unset=True).keys())})

    return fetch_one("SELECT * FROM blog_tags WHERE id = ?", (tag_id,))


@router.delete("/blog/tags/{tag_id}")
def delete_tag(tag_id: str, current_admin: AdminUser) -> dict:
    tag = fetch_one("SELECT id, name FROM blog_tags WHERE id = ?", (tag_id,))
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    execute("DELETE FROM blog_tags WHERE id = ?", (tag_id,))
    _audit(current_admin["id"], "delete_blog_tag", "blog_tag", tag_id, {"name": tag["name"]})
    return {"deleted": True}


# ─── Posts ────────────────────────────────────────────────────────────

@router.get("/blog/posts")
def list_posts(
    current_admin: AdminUser,
    search: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    category_id: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    conditions = ["1=1"]
    params: list = []

    if search:
        conditions.append("(p.title LIKE ? OR p.slug LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if status_filter:
        conditions.append("p.status = ?")
        params.append(status_filter)
    if category_id:
        conditions.append("p.category_id = ?")
        params.append(category_id)

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    rows = fetch_all(
        f"""SELECT p.id, p.slug, p.title, p.excerpt, p.cover_image_url,
                   p.author_name, p.category_id, p.status, p.published_at, p.created_at
            FROM blog_posts p WHERE {where}
            ORDER BY p.created_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    for row in rows:
        row["category"] = _get_post_category(row.get("category_id"))
        row["tags"] = _get_post_tags(row["id"])

    total = fetch_one(f"SELECT COUNT(*) as count FROM blog_posts p WHERE {where}", tuple(count_params))

    return {"posts": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.post("/blog/posts", status_code=201)
def create_post(body: BlogPostCreate, current_admin: AdminUser) -> dict:
    existing = fetch_one("SELECT id FROM blog_posts WHERE slug = ?", (body.slug,))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")

    post_id = secrets.token_hex(16)
    execute(
        """INSERT INTO blog_posts (id, slug, title, excerpt, content_md, cover_image_url,
                   author_name, author_avatar_url, category_id, seo_title, seo_description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (post_id, body.slug, body.title, body.excerpt, body.content_md, body.cover_image_url,
         body.author_name, body.author_avatar_url, body.category_id, body.seo_title, body.seo_description),
    )
    if body.tag_ids:
        _set_post_tags(post_id, body.tag_ids)

    _audit(current_admin["id"], "create_blog_post", "blog_post", post_id, {"title": body.title, "slug": body.slug})
    return _enrich_post(fetch_one("SELECT * FROM blog_posts WHERE id = ?", (post_id,)))


@router.get("/blog/posts/{post_id}")
def get_post_detail(post_id: str, current_admin: AdminUser) -> dict:
    row = fetch_one("SELECT * FROM blog_posts WHERE id = ?", (post_id,))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return _enrich_post(row)


@router.put("/blog/posts/{post_id}")
def update_post(post_id: str, body: BlogPostUpdate, current_admin: AdminUser) -> dict:
    post = fetch_one("SELECT id FROM blog_posts WHERE id = ?", (post_id,))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    data = body.model_dump(exclude_unset=True)
    tag_ids = data.pop("tag_ids", None)

    updates: list[str] = []
    params: list = []
    for field, value in data.items():
        updates.append(f"{field} = ?")
        params.append(value)

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(post_id)
        execute(f"UPDATE blog_posts SET {', '.join(updates)} WHERE id = ?", tuple(params))

    if tag_ids is not None:
        _set_post_tags(post_id, tag_ids)

    _audit(current_admin["id"], "update_blog_post", "blog_post", post_id, {"fields": list(body.model_dump(exclude_unset=True).keys())})
    return _enrich_post(fetch_one("SELECT * FROM blog_posts WHERE id = ?", (post_id,)))


@router.delete("/blog/posts/{post_id}")
def delete_post(post_id: str, current_admin: AdminUser) -> dict:
    post = fetch_one("SELECT id, title FROM blog_posts WHERE id = ?", (post_id,))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    execute("DELETE FROM blog_posts WHERE id = ?", (post_id,))
    _audit(current_admin["id"], "delete_blog_post", "blog_post", post_id, {"title": post["title"]})
    return {"deleted": True}


@router.patch("/blog/posts/{post_id}/publish")
def toggle_publish(post_id: str, current_admin: AdminUser) -> dict:
    post = fetch_one("SELECT id, slug, status, published_at FROM blog_posts WHERE id = ?", (post_id,))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post["status"] == "published":
        # Unpublish
        execute(
            "UPDATE blog_posts SET status = 'draft', updated_at = datetime('now') WHERE id = ?",
            (post_id,),
        )
        _audit(current_admin["id"], "unpublish_blog_post", "blog_post", post_id, {})
        return {"status": "draft"}
    else:
        # Publish
        published_at = post["published_at"] or "datetime('now')"
        if post["published_at"]:
            execute(
                "UPDATE blog_posts SET status = 'published', updated_at = datetime('now') WHERE id = ?",
                (post_id,),
            )
        else:
            execute(
                "UPDATE blog_posts SET status = 'published', published_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
                (post_id,),
            )
        _audit(current_admin["id"], "publish_blog_post", "blog_post", post_id, {"slug": post["slug"]})

        # Trigger Google Indexing in background
        try:
            from app.services.google_indexing import notify_url_updated
            from app.core.config import settings
            url = f"{settings.LANDING_URL}/blog/{post['slug']}"
            threading.Thread(target=notify_url_updated, args=(url,), daemon=True).start()
        except Exception:
            pass  # Don't block publish if indexing fails to import

        return {"status": "published"}
