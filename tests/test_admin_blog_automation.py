"""Blog admin API for automation: scopes, idempotent publish/unpublish, slug rules, IndexNow, RSS."""
from __future__ import annotations

import json
import secrets
from email.utils import parsedate_to_datetime
from typing import Any

import pytest

from app.core.database import execute, fetch_all, fetch_one
from app.core.security import create_access_token
from app.routers.admin import blog as admin_blog
from app.services import indexnow
from app.services.automation_tokens import mint_token


def _user(email: str, *, superadmin: bool) -> str:
    org_id, uid = secrets.token_hex(16), secrets.token_hex(16)
    execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, "Org"))
    execute(
        """INSERT INTO users (id, email, password_hash, name, organization_id, user_type, email_verified, is_superadmin)
           VALUES (?, ?, 'x', 'U', ?, ?, 1, ?)""",
        (uid, email, org_id, "company" if superadmin else "developer", int(superadmin)),
    )
    return uid


@pytest.fixture
def superadmin_id() -> str:
    return _user("root@test.com", superadmin=True)


@pytest.fixture
def admin_headers(superadmin_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': superadmin_id, 'type': 'admin'})}"}


def _token(owner: str, scopes: list[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token('routine', scopes, owner)['token']}"}


@pytest.fixture
def pings(monkeypatch) -> list[list[str]]:
    """Capture IndexNow notifications instead of sending them."""
    calls: list[list[str]] = []
    monkeypatch.setattr(admin_blog.indexnow, "notify", lambda urls: calls.append(list(urls)) or True)
    return calls


def _create(client, headers, slug: str = "ai-collaboration-score", **extra: Any):
    body = {"title": "What the score measures", "slug": slug, "content_md": "# Hello\n\nBody.", **extra}
    return client.post("/api/admin/blog/posts", json=body, headers=headers)


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------

def test_write_token_can_draft_but_not_publish(client, superadmin_id, pings):
    writer = _token(superadmin_id, ["blog:write"])
    resp = _create(client, writer)
    assert resp.status_code == 201, resp.text
    post = resp.json()
    assert post["status"] == "draft"
    assert client.post(f"/api/admin/blog/posts/{post['id']}/publish", headers=writer).status_code == 403
    # Deletes and the UI toggle stay superadmin-JWT only.
    assert client.delete(f"/api/admin/blog/posts/{post['id']}", headers=writer).status_code in (401, 403)
    assert client.patch(f"/api/admin/blog/posts/{post['id']}/publish", headers=writer).status_code in (401, 403)
    assert pings == []

    audit = fetch_one("SELECT * FROM admin_audit_log WHERE action = 'create_blog_post'")
    assert audit["admin_user_id"] == superadmin_id
    assert json.loads(audit["details"])["via"] == "token"


def test_publish_token_cannot_write(client, superadmin_id):
    publisher = _token(superadmin_id, ["blog:publish"])
    assert _create(client, publisher).status_code == 403


def test_developer_jwt_rejected(client):
    dev = _user("dev@example.com", superadmin=False)
    headers = {"Authorization": f"Bearer {create_access_token({'sub': dev})}"}
    assert client.get("/api/admin/blog/posts", headers=headers).status_code == 401
    assert client.get("/api/admin/blog/posts").status_code == 401


def test_admin_ui_jwt_still_works_everywhere(client, admin_headers, pings):
    post = _create(client, admin_headers).json()
    assert client.get("/api/admin/blog/posts", headers=admin_headers).status_code == 200
    assert client.get("/api/admin/blog/categories", headers=admin_headers).status_code == 200
    assert client.get("/api/admin/blog/tags", headers=admin_headers).status_code == 200
    assert client.get("/api/admin/blog/images", headers=admin_headers).status_code == 200
    toggled = client.patch(f"/api/admin/blog/posts/{post['id']}/publish", headers=admin_headers)
    assert toggled.json() == {"status": "published"}
    toggled = client.patch(f"/api/admin/blog/posts/{post['id']}/publish", headers=admin_headers)
    assert toggled.json() == {"status": "draft"}
    assert len(pings) == 2  # publish and unpublish both notify
    assert client.delete(f"/api/admin/blog/posts/{post['id']}", headers=admin_headers).status_code == 200


# ---------------------------------------------------------------------------
# Publish / unpublish
# ---------------------------------------------------------------------------

def test_publish_and_unpublish_are_idempotent(client, superadmin_id, pings):
    headers = _token(superadmin_id, ["blog:write", "blog:publish"])
    post = _create(client, headers).json()

    first = client.post(f"/api/admin/blog/posts/{post['id']}/publish", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "published" and first.json()["changed"] is True
    assert first.json()["url"] == "https://www.kodwai.com/blog/ai-collaboration-score"
    published_at = first.json()["published_at"]
    assert published_at

    again = client.post(f"/api/admin/blog/posts/{post['id']}/publish", headers=headers)
    assert again.status_code == 200
    assert again.json()["status"] == "published" and again.json()["changed"] is False
    assert again.json()["published_at"] == published_at
    assert pings == [["https://www.kodwai.com/blog/ai-collaboration-score"]]

    off = client.post(f"/api/admin/blog/posts/{post['id']}/unpublish", headers=headers)
    assert off.json()["status"] == "draft" and off.json()["changed"] is True
    off_again = client.post(f"/api/admin/blog/posts/{post['id']}/unpublish", headers=headers)
    assert off_again.json()["status"] == "draft" and off_again.json()["changed"] is False
    assert len(pings) == 2

    # Republishing keeps the original published_at.
    back = client.post(f"/api/admin/blog/posts/{post['id']}/publish", headers=headers).json()
    assert back["published_at"] == published_at

    actions = [r["action"] for r in fetch_all("SELECT action FROM admin_audit_log WHERE entity_id = ? ORDER BY created_at", (post["id"],))]
    assert actions.count("publish_blog_post") == 2
    assert actions.count("unpublish_blog_post") == 1


def test_publish_refuses_empty_post(client, superadmin_id, pings):
    headers = _token(superadmin_id, ["blog:write", "blog:publish"])
    post = _create(client, headers, content_md="").json()
    resp = client.post(f"/api/admin/blog/posts/{post['id']}/publish", headers=headers)
    assert resp.status_code == 422
    assert fetch_one("SELECT status FROM blog_posts WHERE id = ?", (post["id"],))["status"] == "draft"
    assert pings == []


def test_publish_unknown_post_is_404(client, superadmin_id):
    headers = _token(superadmin_id, ["blog:publish"])
    assert client.post("/api/admin/blog/posts/nope/publish", headers=headers).status_code == 404
    assert client.post("/api/admin/blog/posts/nope/unpublish", headers=headers).status_code == 404


def test_updating_published_post_pings_indexnow(client, superadmin_id, pings):
    headers = _token(superadmin_id, ["blog:write", "blog:publish"])
    post = _create(client, headers).json()
    client.put(f"/api/admin/blog/posts/{post['id']}", json={"excerpt": "draft edit"}, headers=headers)
    assert pings == []
    client.post(f"/api/admin/blog/posts/{post['id']}/publish", headers=headers)
    resp = client.put(f"/api/admin/blog/posts/{post['id']}", json={"content_md": "Updated body."}, headers=headers)
    assert resp.status_code == 200
    assert pings[-1] == ["https://www.kodwai.com/blog/ai-collaboration-score"]
    assert len(pings) == 2


# ---------------------------------------------------------------------------
# Slugs and lookups
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("slug", ["Has-Caps", "has space", "under_score", "emoji-✨", "slash/y", ""])
def test_invalid_slugs_rejected(client, superadmin_id, slug):
    headers = _token(superadmin_id, ["blog:write"])
    assert _create(client, headers, slug=slug).status_code == 422
    assert client.post("/api/admin/blog/tags", json={"name": "T", "slug": slug or "x y"}, headers=headers).status_code == 422
    assert client.post("/api/admin/blog/categories", json={"name": "C", "slug": slug or "x y"}, headers=headers).status_code == 422


def test_slug_conflicts_are_409(client, superadmin_id):
    headers = _token(superadmin_id, ["blog:write"])
    a = _create(client, headers, slug="post-a").json()
    _create(client, headers, slug="post-b")
    assert _create(client, headers, slug="post-a").status_code == 409
    resp = client.put(f"/api/admin/blog/posts/{a['id']}", json={"slug": "post-b"}, headers=headers)
    assert resp.status_code == 409

    t1 = client.post("/api/admin/blog/tags", json={"name": "One", "slug": "one"}, headers=headers).json()
    client.post("/api/admin/blog/tags", json={"name": "Two", "slug": "two"}, headers=headers)
    assert client.put(f"/api/admin/blog/tags/{t1['id']}", json={"slug": "two"}, headers=headers).status_code == 409


def test_draft_slug_can_change_but_published_cannot(client, superadmin_id, pings):
    headers = _token(superadmin_id, ["blog:write", "blog:publish"])
    post = _create(client, headers, slug="first-slug").json()
    renamed = client.put(f"/api/admin/blog/posts/{post['id']}", json={"slug": "second-slug"}, headers=headers)
    assert renamed.status_code == 200 and renamed.json()["slug"] == "second-slug"

    client.post(f"/api/admin/blog/posts/{post['id']}/publish", headers=headers)
    refused = client.put(f"/api/admin/blog/posts/{post['id']}", json={"slug": "third-slug"}, headers=headers)
    assert refused.status_code == 409
    # The admin UI always resends the unchanged slug; that must keep working.
    same = client.put(
        f"/api/admin/blog/posts/{post['id']}", json={"slug": "second-slug", "title": "New title"}, headers=headers,
    )
    assert same.status_code == 200 and same.json()["title"] == "New title"


def test_null_required_field_is_422(client, superadmin_id):
    headers = _token(superadmin_id, ["blog:write"])
    post = _create(client, headers).json()
    assert client.put(f"/api/admin/blog/posts/{post['id']}", json={"title": None}, headers=headers).status_code == 422


def test_get_by_slug(client, superadmin_id):
    headers = _token(superadmin_id, ["blog:write"])
    post = _create(client, headers, slug="find-me").json()
    resp = client.get("/api/admin/blog/posts/by-slug/find-me", headers=headers)
    assert resp.status_code == 200 and resp.json()["id"] == post["id"]
    assert resp.json()["status"] == "draft"
    assert client.get("/api/admin/blog/posts/by-slug/missing", headers=headers).status_code == 404


# ---------------------------------------------------------------------------
# IndexNow service
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = ""


def test_indexnow_noop_without_key(monkeypatch):
    calls: list[Any] = []
    monkeypatch.setattr(indexnow.httpx, "post", lambda *a, **k: calls.append((a, k)))
    assert indexnow.notify(["https://www.kodwai.com/blog/x"]) is False
    assert calls == []


def test_indexnow_payload_shape(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.INDEXNOW_KEY", "b8769b2b667d49da7b546dde47009a36")
    calls: list[tuple[tuple, dict]] = []

    def _post(*args: Any, **kwargs: Any) -> _Resp:
        calls.append((args, kwargs))
        return _Resp(202)

    monkeypatch.setattr(indexnow.httpx, "post", _post)
    ok = indexnow.notify([
        "https://www.kodwai.com/blog/a",
        "https://www.kodwai.com/blog/a",  # duplicate dropped
        "https://kodwai.com/blog/b",  # apex, not the key host
        "http://localhost:3001/blog/c",
    ])
    assert ok is True
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == "https://api.indexnow.org/indexnow"
    assert kwargs["json"] == {
        "host": "www.kodwai.com",
        "key": "b8769b2b667d49da7b546dde47009a36",
        "keyLocation": "https://www.kodwai.com/b8769b2b667d49da7b546dde47009a36.txt",
        "urlList": ["https://www.kodwai.com/blog/a"],
    }
    assert kwargs["timeout"] > 0


def test_indexnow_never_raises(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.INDEXNOW_KEY", "k")

    def _boom(*a: Any, **k: Any) -> None:
        raise OSError("network down")

    monkeypatch.setattr(indexnow.httpx, "post", _boom)
    assert indexnow.notify(["https://www.kodwai.com/blog/a"]) is False
    monkeypatch.setattr(indexnow.httpx, "post", lambda *a, **k: _Resp(403))
    assert indexnow.notify(["https://www.kodwai.com/blog/a"]) is False
    assert indexnow.notify([]) is False


# ---------------------------------------------------------------------------
# Public RSS
# ---------------------------------------------------------------------------

def test_rss_uses_rfc822_dates_and_www_links(client, monkeypatch):
    # An explicit apex LANDING_URL must still produce canonical www links.
    monkeypatch.setattr("app.core.config.settings.LANDING_URL", "https://kodwai.com")
    execute(
        """INSERT INTO blog_posts (id, slug, title, status, published_at)
           VALUES ('p1', 'hello-world', 'Hello', 'published', '2026-09-20 14:05:00')""",
    )
    execute("INSERT INTO blog_posts (id, slug, title, status) VALUES ('p2', 'secret-draft', 'Draft', 'draft')")
    resp = client.get("/api/blog/rss")
    assert resp.status_code == 200
    xml = resp.text
    assert "<link>https://www.kodwai.com/blog/hello-world</link>" in xml
    assert "https://kodwai.com/" not in xml
    assert "secret-draft" not in xml
    assert "<pubDate>Sun, 20 Sep 2026 14:05:00 GMT</pubDate>" in xml
    pub = xml.split("<pubDate>")[1].split("</pubDate>")[0]
    assert parsedate_to_datetime(pub).year == 2026
