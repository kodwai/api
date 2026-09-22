"""Public challenge detail and rubric routes only serve published (is_public = 1) challenges."""
from __future__ import annotations

import secrets

from app.core.database import execute


def _challenge(slug: str, *, public: bool) -> str:
    org_id, uid, cid = secrets.token_hex(16), secrets.token_hex(16), secrets.token_hex(16)
    execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, "Org"))
    execute(
        "INSERT INTO users (id, email, password_hash, name, organization_id) VALUES (?, ?, 'x', 'U', ?)",
        (uid, f"{slug}@example.com", org_id),
    )
    execute(
        """INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category, is_public)
           VALUES (?, ?, 'T', ?, 'd', 'secret problem', 'easy', 'backend', ?)""",
        (cid, uid, slug, int(public)),
    )
    return cid


def test_draft_challenge_404s_by_slug_and_id(client):
    cid = _challenge("unreleased-draft", public=False)
    for ref in ("unreleased-draft", cid):
        assert client.get(f"/api/challenges/{ref}").status_code == 404
        assert client.get(f"/api/challenges/{ref}/rubric").status_code == 404


def test_public_challenge_still_served(client):
    cid = _challenge("released-one", public=True)
    for ref in ("released-one", cid):
        resp = client.get(f"/api/challenges/{ref}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["slug"] == "released-one"
        assert resp.json()["problem_statement_md"] is None
        assert client.get(f"/api/challenges/{ref}/rubric").status_code == 200
