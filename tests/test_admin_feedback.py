"""Admin feedback inbox and emailed replies, plus the instant acknowledgment. Resend is mocked."""
from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from app.core.database import execute, fetch_all, fetch_one
from app.core.security import create_access_token
from app.services import email_service, feedback_emails
from app.services.automation_tokens import mint_token

EM_DASH = "—"


class FakeResend:
    """Stands in for resend.Emails.send and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        self.fail_with: Exception | None = None

    def send(self, params: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((params, options))
        if self.fail_with is not None:
            raise self.fail_with
        return {"id": f"re_{len(self.calls)}"}


@pytest.fixture
def fake_resend(monkeypatch) -> FakeResend:
    fake = FakeResend()
    monkeypatch.setattr(email_service.resend.Emails, "send", fake.send)
    return fake


@pytest.fixture
def mail_configured(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "founder@example.com")


def _user(email: str, *, superadmin: bool = False, name: str = "Jane Doe") -> str:
    org_id, uid = secrets.token_hex(16), secrets.token_hex(16)
    execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, "Org"))
    execute(
        """INSERT INTO users (id, email, password_hash, name, organization_id, user_type, email_verified, is_superadmin)
           VALUES (?, ?, 'x', ?, ?, ?, 1, ?)""",
        (uid, email, name, org_id, "company" if superadmin else "developer", int(superadmin)),
    )
    return uid


def _challenge(owner: str, title: str = "Bookshelf API") -> str:
    cid = secrets.token_hex(16)
    execute(
        """INSERT INTO challenges (id, created_by, title, slug, description, problem_statement_md, difficulty, category)
           VALUES (?, ?, ?, ?, 'd', 'p', 'easy', 'backend')""",
        (cid, owner, title, f"c-{cid[:8]}"),
    )
    return cid


def _platform_feedback(uid: str, description: str = "The CLI crashed when I ran submit <twice>.", **cols: Any) -> str:
    fid = secrets.token_hex(16)
    execute(
        "INSERT INTO platform_feedback (id, user_id, category, description, rating, status) VALUES (?, ?, ?, ?, ?, ?)",
        (fid, uid, cols.get("category", "bug_report"), description, cols.get("rating", 3), cols.get("status", "new")),
    )
    return fid


def _challenge_feedback(uid: str, cid: str, comment: str | None = "Tests were unclear.") -> str:
    fid = secrets.token_hex(16)
    execute(
        "INSERT INTO challenge_feedback (id, challenge_id, user_id, rating_overall, comment) VALUES (?, ?, ?, 4, ?)",
        (fid, cid, uid, comment),
    )
    return fid


@pytest.fixture
def superadmin_id() -> str:
    return _user("root@test.com", superadmin=True, name="Root")


@pytest.fixture
def admin_headers(superadmin_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': superadmin_id, 'type': 'admin'})}"}


def _token(owner: str, scopes: list[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token('routine', scopes, owner)['token']}"}


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

def test_inbox_lists_both_kinds(client, superadmin_id):
    dev = _user("dev@example.com")
    cid = _challenge(superadmin_id)
    pf = _platform_feedback(dev)
    cf = _challenge_feedback(dev, cid)

    resp = client.get("/api/admin/feedback/inbox", headers=_token(superadmin_id, ["feedback:read"]))
    assert resp.status_code == 200, resp.text
    items = {i["id"]: i for i in resp.json()["items"]}
    assert items[pf]["kind"] == "platform"
    assert items[pf]["user_email"] == "dev@example.com"
    assert items[pf]["user_name"] == "Jane Doe"
    assert items[pf]["category"] == "bug_report"
    assert items[pf]["message"].startswith("The CLI crashed")
    assert items[pf]["status"] == "new"
    assert items[cf]["kind"] == "challenge"
    assert items[cf]["challenge_id"] == cid
    assert items[cf]["challenge_title"] == "Bookshelf API"
    assert items[cf]["rating"] == 4
    assert items[cf]["message"] == "Tests were unclear."
    for key in ("submission_id", "admin_response", "reply_emailed_at", "created_at"):
        assert key in items[pf] and key in items[cf]


def test_inbox_unreplied_filter(client, superadmin_id):
    dev = _user("dev@example.com")
    cid = _challenge(superadmin_id)
    open_pf = _platform_feedback(dev)
    answered_pf = _platform_feedback(dev)
    execute("UPDATE platform_feedback SET admin_response = 'done' WHERE id = ?", (answered_pf,))
    emailed_pf = _platform_feedback(dev)
    execute("UPDATE platform_feedback SET reply_emailed_at = datetime('now') WHERE id = ?", (emailed_pf,))
    dismissed_pf = _platform_feedback(dev, status="dismissed")
    rating_only = _challenge_feedback(dev, cid, comment=None)
    commented = _challenge_feedback(_user("dev2@example.com"), cid)

    resp = client.get("/api/admin/feedback/inbox?unreplied=true", headers=_token(superadmin_id, ["feedback:read"]))
    ids = {i["id"] for i in resp.json()["items"]}
    assert ids == {open_pf, commented}
    assert not ids & {answered_pf, emailed_pf, dismissed_pf, rating_only}


def test_inbox_since_filter(client, superadmin_id):
    dev = _user("dev@example.com")
    old = _platform_feedback(dev)
    execute("UPDATE platform_feedback SET created_at = '2026-01-01 10:00:00' WHERE id = ?", (old,))
    new = _platform_feedback(dev)
    resp = client.get("/api/admin/feedback/inbox?since=2026-06-01", headers=_token(superadmin_id, ["feedback:read"]))
    ids = {i["id"] for i in resp.json()["items"]}
    assert new in ids and old not in ids
    bad = client.get("/api/admin/feedback/inbox?since=2026-13-45", headers=_token(superadmin_id, ["feedback:read"]))
    assert bad.status_code == 422


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

def test_inbox_requires_feedback_read_scope(client, superadmin_id):
    assert client.get("/api/admin/feedback/inbox").status_code == 401
    wrong = client.get("/api/admin/feedback/inbox", headers=_token(superadmin_id, ["feedback:reply"]))
    assert wrong.status_code == 403
    dev = _user("dev@example.com")
    dev_jwt = {"Authorization": f"Bearer {create_access_token({'sub': dev})}"}
    assert client.get("/api/admin/feedback/inbox", headers=dev_jwt).status_code == 401
    forged = {"Authorization": f"Bearer {create_access_token({'sub': dev, 'type': 'admin'})}"}
    assert client.get("/api/admin/feedback/inbox", headers=forged).status_code == 403


def test_reply_requires_feedback_reply_scope(client, superadmin_id):
    fid = _platform_feedback(_user("dev@example.com"))
    resp = client.post(
        f"/api/admin/feedback/platform/{fid}/reply",
        json={"message": "Thanks", "dry_run": True},
        headers=_token(superadmin_id, ["feedback:read"]),
    )
    assert resp.status_code == 403


def test_superadmin_jwt_can_read_and_reply(client, admin_headers):
    fid = _platform_feedback(_user("dev@example.com"))
    assert client.get("/api/admin/feedback/inbox", headers=admin_headers).status_code == 200
    resp = client.post(
        f"/api/admin/feedback/platform/{fid}/reply",
        json={"message": "Thanks", "dry_run": True},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# Replies
# ---------------------------------------------------------------------------

def test_reply_dry_run_previews_without_sending(client, superadmin_id, fake_resend, mail_configured):
    fid = _platform_feedback(_user("dev@example.com"))
    resp = client.post(
        f"/api/admin/feedback/platform/{fid}/reply",
        json={"message": "Thanks for the report. I can reproduce it.", "dry_run": True},
        headers=_token(superadmin_id, ["feedback:reply"]),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["dry_run"] is True
    assert body["kind"] == "platform" and body["id"] == fid
    assert body["email_send_id"] is None
    assert body["email_status"] == "dry_run"
    preview = body["preview"]
    assert preview["subject"] == "Re: your feedback on kodwai"
    assert preview["text"].startswith("Hi Jane,")
    assert "Thanks for the report. I can reproduce it." in preview["text"]
    assert "> The CLI crashed when I ran submit <twice>." in preview["text"]
    assert "\nHakan\n" in preview["text"]
    assert EM_DASH not in preview["text"] and EM_DASH not in preview["subject"]

    assert fake_resend.calls == []
    assert fetch_all("SELECT id FROM email_sends") == []
    row = fetch_one("SELECT admin_response, status, reply_emailed_at FROM platform_feedback WHERE id = ?", (fid,))
    assert row == {"admin_response": None, "status": "new", "reply_emailed_at": None}
    assert fetch_all("SELECT id FROM admin_audit_log WHERE action = 'reply_feedback'") == []


def test_reply_sends_email_and_records_everything(client, superadmin_id, fake_resend, mail_configured):
    dev = _user("dev@example.com")
    fid = _platform_feedback(dev)
    token = mint_token("routine", ["feedback:reply"], superadmin_id)
    resp = client.post(
        f"/api/admin/feedback/platform/{fid}/reply",
        json={"message": "Thanks, fixed in the latest CLI."},
        headers={"Authorization": f"Bearer {token['token']}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True and body["dry_run"] is False
    assert body["email_status"] == "sent"
    assert body["email_send_id"]

    assert len(fake_resend.calls) == 1
    params, options = fake_resend.calls[0]
    assert params["to"] == ["dev@example.com"]
    assert params["reply_to"] == "founder@example.com"
    assert params["subject"] == "Re: your feedback on kodwai"
    # The user's original text is quoted and escaped in the HTML part.
    assert "submit &lt;twice&gt;." in params["html"]
    assert "<twice>" not in params["html"]
    assert "List-Unsubscribe" in params["headers"]
    assert options["idempotency_key"].startswith(f"feedback_reply:platform:{fid}:")

    send = fetch_one("SELECT * FROM email_sends WHERE id = ?", (body["email_send_id"],))
    assert send["template"] == "feedback_reply" and send["stream"] == "feedback" and send["status"] == "sent"
    assert send["user_id"] == dev

    row = fetch_one("SELECT * FROM platform_feedback WHERE id = ?", (fid,))
    assert row["admin_response"] == "Thanks, fixed in the latest CLI."
    assert row["admin_responded_by"] == superadmin_id
    assert row["admin_responded_at"]
    assert row["status"] == "resolved"
    assert row["reply_emailed_at"]
    assert row["reply_email_send_id"] == body["email_send_id"]

    audit = fetch_one("SELECT * FROM admin_audit_log WHERE action = 'reply_feedback' AND entity_id = ?", (fid,))
    assert audit["admin_user_id"] == superadmin_id
    details = json.loads(audit["details"])
    assert details["via"] == "token" and details["token_id"] == token["id"]
    assert details["email_status"] == "sent"


def test_reply_retry_is_deduped(client, superadmin_id, fake_resend, mail_configured):
    fid = _platform_feedback(_user("dev@example.com"))
    headers = _token(superadmin_id, ["feedback:reply"])
    payload = {"message": "Thanks, fixed."}
    first = client.post(f"/api/admin/feedback/platform/{fid}/reply", json=payload, headers=headers).json()
    second = client.post(f"/api/admin/feedback/platform/{fid}/reply", json=payload, headers=headers).json()
    assert first["email_status"] == "sent"
    assert second["email_status"] == "duplicate"
    assert second["ok"] is True
    assert second["email_send_id"] == first["email_send_id"]
    assert len(fake_resend.calls) == 1
    assert len(fetch_all("SELECT id FROM email_sends")) == 1

    # A dry run of the same message now reports the duplicate instead of a fresh send.
    dry = client.post(
        f"/api/admin/feedback/platform/{fid}/reply", json={**payload, "dry_run": True}, headers=headers,
    ).json()
    assert dry["email_status"] == "duplicate"

    # A different message is a different email.
    third = client.post(
        f"/api/admin/feedback/platform/{fid}/reply", json={"message": "One more thing."}, headers=headers,
    ).json()
    assert third["email_status"] == "sent"
    assert len(fake_resend.calls) == 2


def test_reply_refused_send_leaves_item_unreplied(client, superadmin_id, fake_resend, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    # EMAIL_REPLY_TO stays empty (conftest): real feedback sends refuse.
    fid = _platform_feedback(_user("dev@example.com"))
    resp = client.post(
        f"/api/admin/feedback/platform/{fid}/reply",
        json={"message": "Thanks"},
        headers=_token(superadmin_id, ["feedback:reply"]),
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["ok"] is False
    assert body["email_status"] == "skipped"
    assert body["email_reason"] == "reply_to_unset"
    assert fake_resend.calls == []
    row = fetch_one("SELECT admin_response, status FROM platform_feedback WHERE id = ?", (fid,))
    assert row == {"admin_response": None, "status": "new"}
    inbox = client.get("/api/admin/feedback/inbox?unreplied=true", headers=_token(superadmin_id, ["feedback:read"]))
    assert fid in {i["id"] for i in inbox.json()["items"]}


def test_reply_failed_send_is_retryable(client, superadmin_id, fake_resend, mail_configured):
    fid = _platform_feedback(_user("dev@example.com"))
    headers = _token(superadmin_id, ["feedback:reply"])
    fake_resend.fail_with = RuntimeError("resend down")
    failed = client.post(f"/api/admin/feedback/platform/{fid}/reply", json={"message": "Thanks"}, headers=headers).json()
    assert failed["ok"] is False and failed["email_status"] == "failed"
    assert fetch_one("SELECT admin_response FROM platform_feedback WHERE id = ?", (fid,))["admin_response"] is None

    fake_resend.fail_with = None
    retry = client.post(f"/api/admin/feedback/platform/{fid}/reply", json={"message": "Thanks"}, headers=headers).json()
    assert retry["ok"] is True and retry["email_status"] == "sent"
    assert retry["email_send_id"] == failed["email_send_id"]


def test_reply_without_email_saves_response_only(client, superadmin_id, fake_resend, mail_configured):
    fid = _platform_feedback(_user("dev@example.com"))
    resp = client.post(
        f"/api/admin/feedback/platform/{fid}/reply",
        json={"message": "Noted.", "send_email": False, "status": "reviewed"},
        headers=_token(superadmin_id, ["feedback:reply"]),
    ).json()
    assert resp["ok"] is True and resp["email_status"] is None
    assert fake_resend.calls == []
    row = fetch_one("SELECT admin_response, status, reply_emailed_at FROM platform_feedback WHERE id = ?", (fid,))
    assert row == {"admin_response": "Noted.", "status": "reviewed", "reply_emailed_at": None}


def test_challenge_reply(client, superadmin_id, fake_resend, mail_configured):
    dev = _user("dev@example.com")
    cid = _challenge(superadmin_id, title="Bookshelf API")
    fid = _challenge_feedback(dev, cid, comment="The tests expect <b>200</b> but the spec says 201.")
    resp = client.post(
        f"/api/admin/feedback/challenges/{fid}/reply",
        json={"message": "Good catch. The spec and tests now agree."},
        headers=_token(superadmin_id, ["feedback:reply"]),
    ).json()
    assert resp["ok"] is True and resp["kind"] == "challenge"
    assert resp["preview"]["subject"] == "Re: your feedback on Bookshelf API"
    params, options = fake_resend.calls[0]
    assert "&lt;b&gt;200&lt;/b&gt;" in params["html"]
    assert options["idempotency_key"].startswith(f"feedback_reply:challenge:{fid}:")
    row = fetch_one("SELECT * FROM challenge_feedback WHERE id = ?", (fid,))
    assert row["admin_response"] == "Good catch. The spec and tests now agree."
    assert row["admin_responded_by"] == superadmin_id
    assert row["reply_emailed_at"] and row["reply_email_send_id"] == resp["email_send_id"]


def test_reply_unknown_feedback_is_404(client, superadmin_id):
    resp = client.post(
        "/api/admin/feedback/platform/nope/reply",
        json={"message": "Thanks", "dry_run": True},
        headers=_token(superadmin_id, ["feedback:reply"]),
    )
    assert resp.status_code == 404


def test_reply_blank_message_is_422(client, superadmin_id):
    fid = _platform_feedback(_user("dev@example.com"))
    resp = client.post(
        f"/api/admin/feedback/platform/{fid}/reply",
        json={"message": "   ", "dry_run": True},
        headers=_token(superadmin_id, ["feedback:reply"]),
    )
    assert resp.status_code == 422


def test_existing_put_still_sends_no_email(client, admin_headers, fake_resend, mail_configured):
    fid = _platform_feedback(_user("dev@example.com"))
    resp = client.put(f"/api/admin/feedback/platform/{fid}", json={"admin_response": "Thanks"}, headers=admin_headers)
    assert resp.status_code == 200
    assert fake_resend.calls == []


# ---------------------------------------------------------------------------
# Instant acknowledgment (public feedback routes)
# ---------------------------------------------------------------------------

def _dev_headers(uid: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': uid})}"}


def _flag(on: bool) -> None:
    execute("UPDATE feature_flags SET enabled = ? WHERE key = 'feedback_ack_emails'", (int(on),))


def _submit_platform(client, uid: str) -> dict:
    resp = client.post(
        "/api/feedback/platform",
        json={"category": "bug_report", "description": "Submit hangs after the tests finish."},
        headers=_dev_headers(uid),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_ack_not_sent_while_flag_off(client, fake_resend, mail_configured):
    uid = _user("dev@example.com")
    _submit_platform(client, uid)
    assert fake_resend.calls == []
    assert fetch_all("SELECT id FROM email_sends") == []


def test_ack_not_sent_without_reply_to(client, fake_resend, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    _flag(True)
    _submit_platform(client, _user("dev@example.com"))
    assert fake_resend.calls == []


def test_ack_and_founder_notification_sent_when_enabled(client, fake_resend, mail_configured):
    _flag(True)
    uid = _user("dev@example.com")
    fb = _submit_platform(client, uid)

    assert len(fake_resend.calls) == 2
    by_to = {params["to"][0]: (params, options) for params, options in fake_resend.calls}
    ack, ack_opts = by_to["dev@example.com"]
    assert ack["subject"] == "Thanks for the feedback on kodwai"
    assert "I read every message myself, and I usually get back to people within a day." in ack["text"]
    assert "> Submit hangs after the tests finish." in ack["text"]
    assert ack_opts["idempotency_key"] == f"feedback_ack:platform:{fb['id']}"
    note, note_opts = by_to["founder@example.com"]
    assert note["subject"] == "[feedback] Bug report from Jane Doe"
    assert "dev@example.com" in note["text"]
    assert note_opts["idempotency_key"] == f"feedback_ack_founder:platform:{fb['id']}"
    for params, _ in fake_resend.calls:
        assert EM_DASH not in params["text"] and EM_DASH not in params["subject"]

    templates = {r["template"] for r in fetch_all("SELECT template FROM email_sends WHERE status = 'sent'")}
    assert templates == {"feedback_ack", "feedback_ack_founder"}


def test_challenge_ack_once_per_row_and_only_with_comment(client, fake_resend, mail_configured, superadmin_id):
    _flag(True)
    uid = _user("dev@example.com")
    cid = _challenge(superadmin_id)
    headers = _dev_headers(uid)

    rating_only = client.put(f"/api/challenges/{cid}/feedback", json={"rating_overall": 5}, headers=headers)
    assert rating_only.status_code == 200
    assert fake_resend.calls == []

    first = client.put(
        f"/api/challenges/{cid}/feedback", json={"rating_overall": 4, "comment": "Loved it."}, headers=headers,
    )
    assert first.status_code == 200
    assert len(fake_resend.calls) == 2

    edited = client.put(
        f"/api/challenges/{cid}/feedback", json={"rating_overall": 3, "comment": "Loved it, mostly."}, headers=headers,
    )
    assert edited.status_code == 200
    assert len(fake_resend.calls) == 2  # deduped per feedback row


def test_ack_failure_never_fails_the_request(client, fake_resend, mail_configured, monkeypatch):
    _flag(True)

    def _boom(*args: Any, **kwargs: Any) -> dict:
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(feedback_emails, "render_feedback_ack", _boom)
    fb = _submit_platform(client, _user("dev@example.com"))
    assert fetch_one("SELECT id FROM platform_feedback WHERE id = ?", (fb["id"],))
    assert fake_resend.calls == []


def test_ack_skips_unsubscribed_user(client, fake_resend, mail_configured):
    _flag(True)
    uid = _user("dev@example.com")
    execute("UPDATE users SET email_unsubscribed_at = datetime('now') WHERE id = ?", (uid,))
    _submit_platform(client, uid)
    # The user gets nothing; the founder still hears about it.
    assert [params["to"][0] for params, _ in fake_resend.calls] == ["founder@example.com"]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def test_reply_template_keeps_existing_greeting_and_signoff():
    email = feedback_emails.render_feedback_reply(
        kind="platform", user_name="Jane Doe", message="Hi Jane,\n\nFixed now.\n\nHakan", original="It broke.",
    )
    assert email["text"].count("Hi Jane") == 1
    assert email["text"].count("\nHakan\n") == 1


def test_feedback_emails_sign_as_hakan_never_ege():
    reply = feedback_emails.render_feedback_reply(
        kind="challenge", user_name="Jane Doe", message="Thanks, fixed now.", original="It broke.",
        challenge_title="Bookshelf REST API",
    )
    ack = feedback_emails.render_feedback_ack(kind="platform", user_name="Jane Doe", original="It broke.")
    for email in (reply, ack):
        assert "\n\nHakan\n" in email["text"]
        assert "Hakan<br><span" in email["html"]  # signature block: name, then role
        for part in email.values():
            assert "Ege" not in part


def test_templates_escape_and_strip_header_newlines():
    note = feedback_emails.render_founder_notification(
        kind="challenge", feedback_id="abc", user_name="Eve\r\nBcc: x@y.z", user_email="eve@example.com",
        original="<script>alert(1)</script>", rating=2, challenge_title="Title",
    )
    assert "\n" not in note["subject"] and "\r" not in note["subject"]
    assert "<script>" not in note["html"]
    assert "&lt;script&gt;" in note["html"]
