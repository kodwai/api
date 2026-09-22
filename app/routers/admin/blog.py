from __future__ import annotations

import json
import re
import secrets
from typing import Annotated, Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.core.admin_deps import AdminUser
from app.core.automation_deps import require_scope
from app.core.database import execute, fetch_all, fetch_one
from app.schemas.blog import (
    BlogCategoryCreate,
    BlogCategoryUpdate,
    BlogPostCreate,
    BlogPostUpdate,
    BlogTagCreate,
    BlogTagUpdate,
)
from app.services import indexnow
from app.services.site_urls import blog_post_url

router = APIRouter(tags=["admin-blog"])

# Create/read/update routes accept a superadmin JWT (the admin UI) or an automation token with
# the scope. Deletes and the PATCH publish toggle stay superadmin-JWT only.
BlogWriter = Annotated[dict[str, Any], Depends(require_scope("blog:write"))]
BlogPublisher = Annotated[dict[str, Any], Depends(require_scope("blog:publish"))]

SLUG_RE = re.compile(r"^[a-z0-9-]+$")
# Columns that are NOT NULL in blog_posts: an explicit null in an update is refused, not stored.
_POST_REQUIRED_FIELDS = ("title", "slug", "excerpt", "content_md", "author_name")


# ─── Helpers ──────────────────────────────────────────────────────────

def _audit(principal: dict, action: str, entity_type: str, entity_id: str, details: dict) -> None:
    if principal.get("via") == "token":
        details = {**details, "via": "token", "token_id": principal.get("token_id")}
    audit_id = secrets.token_hex(16)
    execute(
        "INSERT INTO admin_audit_log (id, admin_user_id, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (audit_id, principal["id"], action, entity_type, entity_id, json.dumps(details)),
    )


def _validate_slug(slug: str | None) -> None:
    if slug is None or not SLUG_RE.match(slug):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Slug must contain only lowercase letters, numbers and hyphens",
        )


def _ping_indexnow(background_tasks: BackgroundTasks, slug: str) -> None:
    """Tell IndexNow a public blog URL changed. Runs after the response; never raises."""
    background_tasks.add_task(indexnow.notify, [blog_post_url(slug)])


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
def list_categories(current_admin: BlogWriter) -> list[dict]:
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
def create_category(body: BlogCategoryCreate, current_admin: BlogWriter) -> dict:
    _validate_slug(body.slug)
    existing = fetch_one("SELECT id FROM blog_categories WHERE slug = ?", (body.slug,))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category slug already exists")

    cat_id = secrets.token_hex(16)
    execute(
        "INSERT INTO blog_categories (id, name, slug, description, sort_order) VALUES (?, ?, ?, ?, ?)",
        (cat_id, body.name, body.slug, body.description, body.sort_order),
    )
    _audit(current_admin, "create_blog_category", "blog_category", cat_id, {"name": body.name})
    return fetch_one("SELECT * FROM blog_categories WHERE id = ?", (cat_id,))


@router.put("/blog/categories/{category_id}")
def update_category(category_id: str, body: BlogCategoryUpdate, current_admin: BlogWriter) -> dict:
    cat = fetch_one("SELECT id FROM blog_categories WHERE id = ?", (category_id,))
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    data = body.model_dump(exclude_unset=True)
    if "slug" in data:
        _validate_slug(data["slug"])
        if fetch_one("SELECT id FROM blog_categories WHERE slug = ? AND id != ?", (data["slug"], category_id)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category slug already exists")

    updates: list[str] = []
    params: list = []
    for field, value in data.items():
        updates.append(f"{field} = ?")
        params.append(value)

    if updates:
        params.append(category_id)
        execute(f"UPDATE blog_categories SET {', '.join(updates)} WHERE id = ?", tuple(params))
        _audit(current_admin, "update_blog_category", "blog_category", category_id, {"fields": list(data.keys())})

    return fetch_one("SELECT * FROM blog_categories WHERE id = ?", (category_id,))


@router.delete("/blog/categories/{category_id}")
def delete_category(category_id: str, current_admin: AdminUser) -> dict:
    cat = fetch_one("SELECT id, name FROM blog_categories WHERE id = ?", (category_id,))
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    execute("DELETE FROM blog_categories WHERE id = ?", (category_id,))
    _audit(current_admin, "delete_blog_category", "blog_category", category_id, {"name": cat["name"]})
    return {"deleted": True}


# ─── Tags ─────────────────────────────────────────────────────────────

@router.get("/blog/tags")
def list_tags(current_admin: BlogWriter) -> list[dict]:
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
def create_tag(body: BlogTagCreate, current_admin: BlogWriter) -> dict:
    _validate_slug(body.slug)
    existing = fetch_one("SELECT id FROM blog_tags WHERE slug = ?", (body.slug,))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tag slug already exists")

    tag_id = secrets.token_hex(16)
    execute(
        "INSERT INTO blog_tags (id, name, slug) VALUES (?, ?, ?)",
        (tag_id, body.name, body.slug),
    )
    _audit(current_admin, "create_blog_tag", "blog_tag", tag_id, {"name": body.name})
    return fetch_one("SELECT * FROM blog_tags WHERE id = ?", (tag_id,))


@router.put("/blog/tags/{tag_id}")
def update_tag(tag_id: str, body: BlogTagUpdate, current_admin: BlogWriter) -> dict:
    tag = fetch_one("SELECT id FROM blog_tags WHERE id = ?", (tag_id,))
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")

    data = body.model_dump(exclude_unset=True)
    if "slug" in data:
        _validate_slug(data["slug"])
        if fetch_one("SELECT id FROM blog_tags WHERE slug = ? AND id != ?", (data["slug"], tag_id)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tag slug already exists")

    updates: list[str] = []
    params: list = []
    for field, value in data.items():
        updates.append(f"{field} = ?")
        params.append(value)

    if updates:
        params.append(tag_id)
        execute(f"UPDATE blog_tags SET {', '.join(updates)} WHERE id = ?", tuple(params))
        _audit(current_admin, "update_blog_tag", "blog_tag", tag_id, {"fields": list(data.keys())})

    return fetch_one("SELECT * FROM blog_tags WHERE id = ?", (tag_id,))


@router.delete("/blog/tags/{tag_id}")
def delete_tag(tag_id: str, current_admin: AdminUser) -> dict:
    tag = fetch_one("SELECT id, name FROM blog_tags WHERE id = ?", (tag_id,))
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    execute("DELETE FROM blog_tags WHERE id = ?", (tag_id,))
    _audit(current_admin, "delete_blog_tag", "blog_tag", tag_id, {"name": tag["name"]})
    return {"deleted": True}


# ─── Posts ────────────────────────────────────────────────────────────

@router.get("/blog/posts")
def list_posts(
    current_admin: BlogWriter,
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
def create_post(body: BlogPostCreate, current_admin: BlogWriter) -> dict:
    """Create a draft. Publishing is a separate, explicit step."""
    _validate_slug(body.slug)
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

    _audit(current_admin, "create_blog_post", "blog_post", post_id, {"title": body.title, "slug": body.slug})
    return _enrich_post(fetch_one("SELECT * FROM blog_posts WHERE id = ?", (post_id,)))


@router.get("/blog/posts/by-slug/{slug}")
def get_post_by_slug(slug: str, current_admin: BlogWriter) -> dict:
    """Look a post up by slug (draft or published), so the routine can update instead of duplicate."""
    row = fetch_one("SELECT * FROM blog_posts WHERE slug = ?", (slug,))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return _enrich_post(row)


@router.get("/blog/posts/{post_id}")
def get_post_detail(post_id: str, current_admin: BlogWriter) -> dict:
    row = fetch_one("SELECT * FROM blog_posts WHERE id = ?", (post_id,))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return _enrich_post(row)


@router.put("/blog/posts/{post_id}")
def update_post(
    post_id: str,
    body: BlogPostUpdate,
    current_admin: BlogWriter,
    background_tasks: BackgroundTasks,
) -> dict:
    post = fetch_one("SELECT id, slug, status FROM blog_posts WHERE id = ?", (post_id,))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    data = body.model_dump(exclude_unset=True)
    tag_ids = data.pop("tag_ids", None)

    nulled = [f for f in _POST_REQUIRED_FIELDS if f in data and data[f] is None]
    if nulled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"These fields cannot be null: {', '.join(nulled)}",
        )
    if "slug" in data and data["slug"] != post["slug"]:
        _validate_slug(data["slug"])
        if post["status"] == "published":
            # A published URL may already be indexed and linked. Unpublish first to rename.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot change the slug of a published post. Unpublish it first.",
            )
        if fetch_one("SELECT id FROM blog_posts WHERE slug = ? AND id != ?", (data["slug"], post_id)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")
    else:
        # Unchanged (the admin UI always sends it): nothing to write.
        data.pop("slug", None)

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

    _audit(current_admin, "update_blog_post", "blog_post", post_id, {"fields": list(body.model_dump(exclude_unset=True).keys())})
    if post["status"] == "published" and (updates or tag_ids is not None):
        _ping_indexnow(background_tasks, post["slug"])
    return _enrich_post(fetch_one("SELECT * FROM blog_posts WHERE id = ?", (post_id,)))


@router.delete("/blog/posts/{post_id}")
def delete_post(post_id: str, current_admin: AdminUser, background_tasks: BackgroundTasks) -> dict:
    post = fetch_one("SELECT id, title, slug, status FROM blog_posts WHERE id = ?", (post_id,))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    execute("DELETE FROM blog_posts WHERE id = ?", (post_id,))
    _audit(current_admin, "delete_blog_post", "blog_post", post_id, {"title": post["title"]})
    if post["status"] == "published":
        _ping_indexnow(background_tasks, post["slug"])
    return {"deleted": True}


def _publish(post: dict, principal: dict, background_tasks: BackgroundTasks) -> None:
    # Republishing keeps the original published_at.
    execute(
        """UPDATE blog_posts
           SET status = 'published', published_at = COALESCE(published_at, datetime('now')), updated_at = datetime('now')
           WHERE id = ?""",
        (post["id"],),
    )
    _audit(principal, "publish_blog_post", "blog_post", post["id"], {"slug": post["slug"]})
    _ping_indexnow(background_tasks, post["slug"])


def _unpublish(post: dict, principal: dict, background_tasks: BackgroundTasks) -> None:
    execute(
        "UPDATE blog_posts SET status = 'draft', updated_at = datetime('now') WHERE id = ?",
        (post["id"],),
    )
    _audit(principal, "unpublish_blog_post", "blog_post", post["id"], {"slug": post["slug"]})
    # The URL now 404s; IndexNow accepts removed URLs so engines recrawl and drop it.
    _ping_indexnow(background_tasks, post["slug"])


def _publish_state(post_id: str, changed: bool) -> dict:
    row = _enrich_post(fetch_one("SELECT * FROM blog_posts WHERE id = ?", (post_id,)))
    row["changed"] = changed
    row["url"] = blog_post_url(row["slug"])
    return row


@router.post("/blog/posts/{post_id}/publish")
def publish_post(post_id: str, principal: BlogPublisher, background_tasks: BackgroundTasks) -> dict:
    """Idempotent publish: an already published post is returned unchanged (changed=false)."""
    post = fetch_one("SELECT id, slug, title, content_md, status FROM blog_posts WHERE id = ?", (post_id,))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post["status"] == "published":
        return _publish_state(post_id, changed=False)
    if not (post["title"] or "").strip() or not (post["content_md"] or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A post needs a title and content before it can be published",
        )
    _publish(post, principal, background_tasks)
    return _publish_state(post_id, changed=True)


@router.post("/blog/posts/{post_id}/unpublish")
def unpublish_post(post_id: str, principal: BlogPublisher, background_tasks: BackgroundTasks) -> dict:
    """Idempotent unpublish: a draft is returned unchanged (changed=false)."""
    post = fetch_one("SELECT id, slug, status FROM blog_posts WHERE id = ?", (post_id,))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    if post["status"] != "published":
        return _publish_state(post_id, changed=False)
    _unpublish(post, principal, background_tasks)
    return _publish_state(post_id, changed=True)


@router.patch("/blog/posts/{post_id}/publish")
def toggle_publish(post_id: str, current_admin: AdminUser, background_tasks: BackgroundTasks) -> dict:
    """Admin UI toggle. Not idempotent (a retry flips it back), so automation uses POST
    /publish and /unpublish instead."""
    post = fetch_one("SELECT id, slug, status, published_at FROM blog_posts WHERE id = ?", (post_id,))
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    if post["status"] == "published":
        _unpublish(post, current_admin, background_tasks)
        return {"status": "draft"}
    _publish(post, current_admin, background_tasks)
    return {"status": "published"}
