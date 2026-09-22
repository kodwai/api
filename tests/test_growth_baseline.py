"""GET /api/admin/growth/baseline: demo/internal exclusion, funnel counts, activation states."""
from __future__ import annotations

import secrets

import pytest

from app.core.database import execute
from app.core.security import create_access_token
from app.services.automation_tokens import mint_token


def _user(
    email: str,
    *,
    superadmin: bool = False,
    github: bool = False,
    is_demo: int = 0,
    created_at: str | None = None,
    user_type: str = "developer",
) -> str:
    org_id, uid = secrets.token_hex(16), secrets.token_hex(16)
    execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, "Org"))
    execute(
        """INSERT INTO users (id, email, password_hash, name, organization_id, user_type, email_verified,
                              is_superadmin, github_id, is_demo)
           VALUES (?, ?, 'x', 'U', ?, ?, 1, ?, ?, ?)""",
        (uid, email, org_id, user_type, int(superadmin), f"gh-{uid[:8]}" if github else None, is_demo),
    )
    if created_at:
        execute("UPDATE users SET created_at = ? WHERE id = ?", (created_at, uid))
    return uid


def _challenge(owner: str) -> str:
    cid = secrets.token_hex(16)
    execute(
        """INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category)
           VALUES (?, ?, 'T', ?, 'd', 'p', 'easy', 'backend')""",
        (cid, owner, f"c-{cid[:8]}"),
    )
    return cid


def _cli_login(uid: str) -> None:
    execute(
        "INSERT INTO cli_auth_codes (id, user_id, code, expires_at, used_at) VALUES (?, ?, ?, '2099-01-01T00:00:00+00:00', datetime('now'))",
        (secrets.token_hex(16), uid, secrets.token_hex(8)),
    )


def _submission(uid: str, cid: str, *, scored: bool) -> None:
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id, status, scored_at) VALUES (?, ?, ?, ?, ?)",
        (secrets.token_hex(16), cid, uid, "scored" if scored else "in_progress", "2026-09-21 10:00:00" if scored else None),
    )
    if scored:
        execute("UPDATE submissions SET scored_at = datetime('now') WHERE user_id = ? AND status = 'scored'", (uid,))


@pytest.fixture
def root() -> str:
    return _user("root@test.com", superadmin=True, user_type="company")


@pytest.fixture
def stats_headers(root: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token('routine', ['stats:read'], root)['token']}"}


def test_baseline_counts_real_users_only(client, root, stats_headers, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.INTERNAL_EMAILS", "Team@Kodwai.com, qa@example.com")
    cid = _challenge(root)

    signed_up = _user("a@example.com")
    cli_only = _user("b@example.com", github=True)
    _cli_login(cli_only)
    started = _user("c@example.com", github=True)
    _cli_login(started)
    _submission(started, cid, scored=False)
    scored = _user("d@example.com")
    _cli_login(scored)
    _submission(scored, cid, scored=True)

    # Excluded: demo by email, demo by flag, internal, superadmin.
    demo = _user("seed1@demo.kodwai.dev")
    _cli_login(demo)
    _submission(demo, cid, scored=True)
    flagged = _user("flagged@example.com", is_demo=1)
    _submission(flagged, cid, scored=True)
    internal = _user("team@kodwai.com")
    _submission(internal, cid, scored=True)
    execute(
        "INSERT INTO platform_feedback (id, user_id, category, description) VALUES (?, ?, 'general', 'demo feedback text')",
        (secrets.token_hex(16), demo),
    )
    execute(
        "INSERT INTO platform_feedback (id, user_id, category, description) VALUES (?, ?, 'general', 'real feedback text')",
        (secrets.token_hex(16), signed_up),
    )
    # A real user who signed up long ago still counts toward the all-time total, not the window.
    veteran = _user("old@example.com", created_at="2025-01-01 00:00:00")
    execute(
        "INSERT INTO submissions (id, challenge_id, user_id, status, started_at, scored_at) VALUES (?, ?, ?, 'scored', '2025-02-01 00:00:00', '2025-02-01 01:00:00')",
        (secrets.token_hex(16), cid, veteran),
    )

    resp = client.get("/api/admin/growth/baseline?since=2026-01-01", headers=stats_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["since"] == "2026-01-01"
    assert body["generated_at"]
    assert body["signups"]["total"] == 4
    assert body["signups"]["by_method"] == {"github": 2, "email": 2}
    assert body["cli_logins"] == 3
    assert body["submissions"]["started"] == 2
    assert body["submissions"]["scored"] == 1
    assert body["feedback"]["new"] == 1
    assert body["real_scored_submissions_total"] == 2

    states = {u["user_id"]: u["state"] for u in body["new_users"]}
    assert states == {signed_up: "signed_up", cli_only: "cli_login", started: "submission_started", scored: "scored"}
    assert body["signups"]["by_state"] == {"signed_up": 1, "cli_login": 1, "submission_started": 1, "scored": 1}
    masked = {u["masked_email"] for u in body["new_users"]}
    assert "a***@example.com" in masked
    assert not any("demo.kodwai.dev" in m or "kodwai.com" in m for m in masked)
    assert all("@" in m and "***" in m for m in masked)


def test_baseline_email_send_summary(client, stats_headers):
    execute(
        """INSERT INTO email_sends (to_email, template, stream, dedupe_key, status, sent_at) VALUES
           ('a@x.com', 'welcome', 'lifecycle', 'k1', 'sent', datetime('now')),
           ('b@x.com', 'welcome', 'lifecycle', 'k2', 'failed', NULL),
           ('c@x.com', 'feedback_reply', 'feedback', 'k3', 'sent', datetime('now')),
           ('d@x.com', 'welcome', 'lifecycle', 'k4', 'sent', '2026-01-02 00:00:00')""",
    )
    body = client.get("/api/admin/growth/baseline", headers=stats_headers).json()
    assert body["email_sends"]["by_template_status"]["welcome"] == {"sent": 2, "failed": 1}
    assert body["email_sends"]["by_template_status"]["feedback_reply"] == {"sent": 1}
    assert body["resend_sends_today"] == 2


def test_baseline_default_window_and_validation(client, stats_headers):
    body = client.get("/api/admin/growth/baseline", headers=stats_headers).json()
    assert len(body["since"]) == 10
    assert client.get("/api/admin/growth/baseline?since=yesterday", headers=stats_headers).status_code == 422
    assert client.get("/api/admin/growth/baseline?since=2026-02-30", headers=stats_headers).status_code == 422


def test_baseline_requires_stats_scope(client, root):
    assert client.get("/api/admin/growth/baseline").status_code == 401
    wrong = {"Authorization": f"Bearer {mint_token('r', ['email:read'], root)['token']}"}
    assert client.get("/api/admin/growth/baseline", headers=wrong).status_code == 403
    dev = _user("dev@example.com")
    dev_jwt = {"Authorization": f"Bearer {create_access_token({'sub': dev})}"}
    assert client.get("/api/admin/growth/baseline", headers=dev_jwt).status_code == 401
    admin_jwt = {"Authorization": f"Bearer {create_access_token({'sub': root, 'type': 'admin'})}"}
    assert client.get("/api/admin/growth/baseline", headers=admin_jwt).status_code == 200
