from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# --- Categories ---

class BlogCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)
    description: str = ""
    sort_order: int = 0


class BlogCategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    slug: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    sort_order: Optional[int] = None


class BlogCategoryResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str = ""
    sort_order: int = 0
    post_count: int = 0
    created_at: str


# --- Tags ---

class BlogTagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=100)


class BlogTagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    slug: Optional[str] = Field(default=None, max_length=100)


class BlogTagResponse(BaseModel):
    id: str
    name: str
    slug: str
    post_count: int = 0
    created_at: str


# --- Posts ---

class BlogPostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=255)
    excerpt: str = ""
    content_md: str = ""
    cover_image_url: Optional[str] = None
    author_name: str = "Kodwai Team"
    author_avatar_url: Optional[str] = None
    category_id: Optional[str] = None
    tag_ids: list[str] = Field(default_factory=list)
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None


class BlogPostUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    slug: Optional[str] = Field(default=None, max_length=255)
    excerpt: Optional[str] = None
    content_md: Optional[str] = None
    cover_image_url: Optional[str] = None
    author_name: Optional[str] = None
    author_avatar_url: Optional[str] = None
    category_id: Optional[str] = None
    tag_ids: Optional[list[str]] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None


class BlogPostTagResponse(BaseModel):
    id: str
    name: str
    slug: str


class BlogPostCategoryResponse(BaseModel):
    id: str
    name: str
    slug: str


class BlogPostResponse(BaseModel):
    id: str
    slug: str
    title: str
    excerpt: str = ""
    content_md: str = ""
    cover_image_url: Optional[str] = None
    author_name: str = "Kodwai Team"
    author_avatar_url: Optional[str] = None
    category: Optional[BlogPostCategoryResponse] = None
    tags: list[BlogPostTagResponse] = Field(default_factory=list)
    status: str = "draft"
    published_at: Optional[str] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    created_at: str
    updated_at: str


class BlogPostListResponse(BaseModel):
    id: str
    slug: str
    title: str
    excerpt: str = ""
    cover_image_url: Optional[str] = None
    author_name: str = "Kodwai Team"
    category: Optional[BlogPostCategoryResponse] = None
    tags: list[BlogPostTagResponse] = Field(default_factory=list)
    status: str = "draft"
    published_at: Optional[str] = None
    created_at: str


# --- Images ---

class BlogImageResponse(BaseModel):
    id: str
    url: str
    filename: str
    original_name: str
    mime_type: str
    size_bytes: int
    created_at: str
