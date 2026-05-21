from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.core.config import settings
from app.core.database import fetch_all, fetch_one

router = APIRouter(tags=["blog"])


# ─── Helpers ──────────────────────────────────────────────────────────

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


def _enrich_post(row: dict) -> dict:
    row["category"] = _get_post_category(row.get("category_id"))
    row["tags"] = _get_post_tags(row["id"])
    return row


# ─── Public endpoints ─────────────────────────────────────────────────

@router.get("/blog")
def list_published_posts(
    category: Optional[str] = None,
    tag: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(12, ge=1, le=50),
) -> dict:
    """List published blog posts, newest first."""
    conditions = ["p.status = 'published'"]
    params: list = []
    joins = ""

    if category:
        conditions.append("c.slug = ?")
        params.append(category)
        joins += " LEFT JOIN blog_categories c ON c.id = p.category_id"
    if tag:
        conditions.append("t.slug = ?")
        params.append(tag)
        joins += " JOIN blog_post_tags pt ON pt.post_id = p.id JOIN blog_tags t ON t.id = pt.tag_id"

    where = " AND ".join(conditions)
    offset = (page - 1) * limit
    count_params = list(params)
    params.extend([limit, offset])

    # Need LEFT JOIN for category even without filter to get category info
    base_join = joins if joins else ""
    if category:
        # Already have the join
        pass
    else:
        base_join = joins

    rows = fetch_all(
        f"""SELECT DISTINCT p.id, p.slug, p.title, p.excerpt, p.cover_image_url,
                   p.author_name, p.category_id, p.status, p.published_at, p.created_at
            FROM blog_posts p{base_join}
            WHERE {where}
            ORDER BY p.published_at DESC LIMIT ? OFFSET ?""",
        tuple(params),
    )
    for row in rows:
        row["category"] = _get_post_category(row.get("category_id"))
        row["tags"] = _get_post_tags(row["id"])

    total = fetch_one(
        f"SELECT COUNT(DISTINCT p.id) as count FROM blog_posts p{base_join} WHERE {where}",
        tuple(count_params),
    )

    return {"posts": rows, "total": total["count"] if total else 0, "page": page, "limit": limit}


@router.get("/blog/categories")
def list_public_categories() -> list[dict]:
    """List categories that have at least one published post."""
    return fetch_all(
        """SELECT c.id, c.name, c.slug, c.description, c.sort_order,
                  COUNT(p.id) as post_count
           FROM blog_categories c
           JOIN blog_posts p ON p.category_id = c.id AND p.status = 'published'
           GROUP BY c.id
           ORDER BY c.sort_order, c.name""",
        (),
    )


@router.get("/blog/tags")
def list_public_tags() -> list[dict]:
    """List tags that have at least one published post."""
    return fetch_all(
        """SELECT t.id, t.name, t.slug, COUNT(pt.post_id) as post_count
           FROM blog_tags t
           JOIN blog_post_tags pt ON pt.tag_id = t.id
           JOIN blog_posts p ON p.id = pt.post_id AND p.status = 'published'
           GROUP BY t.id
           ORDER BY t.name""",
        (),
    )


@router.get("/blog/sitemap")
def blog_sitemap() -> list[dict]:
    """Return slugs and dates for sitemap generation."""
    return fetch_all(
        "SELECT slug, published_at, updated_at FROM blog_posts WHERE status = 'published' ORDER BY published_at DESC",
        (),
    )


@router.get("/blog/rss")
def blog_rss() -> Response:
    """Generate RSS 2.0 feed for published posts."""
    posts = fetch_all(
        """SELECT slug, title, excerpt, author_name, published_at
           FROM blog_posts WHERE status = 'published'
           ORDER BY published_at DESC LIMIT 50""",
        (),
    )

    base_url = settings.LANDING_URL.rstrip("/")
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for p in posts:
        pub_date = p["published_at"] or ""
        link = f"{base_url}/blog/{p['slug']}"
        items.append(
            f"""    <item>
      <title>{xml_escape(p["title"])}</title>
      <link>{xml_escape(link)}</link>
      <description>{xml_escape(p["excerpt"])}</description>
      <author>{xml_escape(p["author_name"])}</author>
      <pubDate>{xml_escape(pub_date)}</pubDate>
      <guid isPermaLink="true">{xml_escape(link)}</guid>
    </item>"""
        )

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>kodwai Blog</title>
    <link>{base_url}/blog</link>
    <description>AI-Agent Coding Challenges for Developers</description>
    <language>en</language>
    <lastBuildDate>{now}</lastBuildDate>
    <atom:link href="{base_url}/blog/rss.xml" rel="self" type="application/rss+xml"/>
{chr(10).join(items)}
  </channel>
</rss>"""

    return Response(content=xml, media_type="application/rss+xml")


@router.get("/blog/{slug}")
def get_published_post(slug: str) -> dict:
    """Get a single published post by slug."""
    row = fetch_one(
        "SELECT * FROM blog_posts WHERE slug = ? AND status = 'published'",
        (slug,),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return _enrich_post(row)
