from __future__ import annotations

import logging
import secrets
import uuid

from fastapi import APIRouter, HTTPException, UploadFile, status

from app.core.admin_deps import AdminUser
from app.core.config import settings
from app.core.database import execute, fetch_all, fetch_one

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin-blog-images"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 5 * 1024 * 1024  # 5MB


@router.post("/blog/images", status_code=201)
async def upload_image(file: UploadFile, current_admin: AdminUser) -> dict:
    """Upload an image to Vercel Blob storage."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_TYPES)}",
        )

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large. Maximum size is 5MB.",
        )

    ext = (file.filename or "image").rsplit(".", 1)[-1] if file.filename and "." in file.filename else "png"
    blob_filename = f"blog/{uuid.uuid4().hex}.{ext}"

    if not settings.BLOB_READ_WRITE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Blob storage not configured (BLOB_READ_WRITE_TOKEN missing)",
        )

    import vercel_blob
    import os
    os.environ["BLOB_READ_WRITE_TOKEN"] = settings.BLOB_READ_WRITE_TOKEN

    try:
        resp = vercel_blob.put(blob_filename, content, {"addRandomSuffix": "false"})
    except Exception as e:
        logger.error("Vercel Blob upload failed: %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Image upload failed")

    blob_url = resp.get("url", "")

    image_id = secrets.token_hex(16)
    execute(
        """INSERT INTO blog_images (id, filename, original_name, mime_type, size_bytes, url, uploaded_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (image_id, blob_filename, file.filename or "image", file.content_type, len(content), blob_url, current_admin["id"]),
    )

    return fetch_one("SELECT * FROM blog_images WHERE id = ?", (image_id,))


@router.get("/blog/images")
def list_images(current_admin: AdminUser) -> list[dict]:
    """List all uploaded blog images."""
    return fetch_all("SELECT * FROM blog_images ORDER BY created_at DESC", ())


@router.delete("/blog/images/{image_id}")
def delete_image(image_id: str, current_admin: AdminUser) -> dict:
    """Delete an image from Vercel Blob and database."""
    image = fetch_one("SELECT * FROM blog_images WHERE id = ?", (image_id,))
    if image is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    if settings.BLOB_READ_WRITE_TOKEN and image["url"]:
        import vercel_blob
        import os
        os.environ["BLOB_READ_WRITE_TOKEN"] = settings.BLOB_READ_WRITE_TOKEN
        try:
            vercel_blob.delete([image["url"]])
        except Exception as e:
            logger.warning("Failed to delete blob: %s", e)

    execute("DELETE FROM blog_images WHERE id = ?", (image_id,))
    return {"deleted": True}
