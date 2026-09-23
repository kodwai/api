"""send_tracked (claim-then-send ledger), unsubscribe tokens and email helpers. Resend is mocked."""
from __future__ import annotations

import secrets
import threading
from typing import Any

import pytest

from app.core.database import execute, fetch_all, fetch_one
from app.services import email_service
from app.services.email_service import (
    mask_email,
    send_tracked,
    unsubscribe_token,
    unsubscribe_url,
    verify_unsubscribe_token,
    with_utm,
)


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
def configured(monkeypatch):
    """Everything a real lifecycle send needs, with the kill switches flipped on."""
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "founder@example.com")
    execute("UPDATE feature_flags SET enabled = 1 WHERE key IN ('lifecycle_emails', 'feedback_ack_emails')")


def _user(email: str = "dev@example.com") -> str:
    org_id, uid = secrets.token_hex(16), secrets.token_hex(16)
    execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, "Org"))
    execute(
        "INSERT INTO users (id, email, password_hash, name, organization_id, user_type, email_verified) VALUES (?, ?, 'x', 'U', ?, 'developer', 1)",
        (uid, email, org_id),
    )
    return uid


def _send(uid: str | None, **overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "user_id": uid, "to": "dev@example.com", "template": "welcome", "subject": "Hi",
        "html": "<p>Hi</p>", "text": "Hi", "stream": "lifecycle", "dedupe_key": f"welcome:{uid}",
    }
    kwargs.update(overrides)
    return send_tracked(**kwargs)


# ---------------------------------------------------------------------------
# Claim-then-send and dedupe
# ---------------------------------------------------------------------------

def test_send_records_row_and_calls_resend(fake_resend, configured):
    uid = _user()
    result = _send(uid, run_id="run-1", meta={"why": "test"})
    assert result["status"] == "sent"
    assert result["provider_id"] == "re_1"

    row = fetch_one("SELECT * FROM email_sends WHERE id = ?", (result["email_send_id"],))
    assert row["status"] == "sent" and row["provider_id"] == "re_1" and row["sent_at"]
    assert row["user_id"] == uid and row["template"] == "welcome" and row["stream"] == "lifecycle"
    assert row["run_id"] == "run-1" and row["attempts"] == 1

    params, options = fake_resend.calls[0]
    assert options == {"idempotency_key": f"welcome:{uid}"}
    assert params["from"] == '"Hakan from Kodwai" <hi@updates.kodwai.com>'
    assert params["reply_to"] == "founder@example.com"
    assert params["to"] == ["dev@example.com"]
    assert params["text"] == "Hi" and params["html"] == "<p>Hi</p>"
    assert {"name": "template", "value": "welcome"} in params["tags"]
    assert params["headers"]["List-Unsubscribe"] == f"<{unsubscribe_url(uid)}>"
    assert params["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_same_dedupe_key_sends_once(fake_resend, configured):
    uid = _user()
    assert _send(uid)["status"] == "sent"
    second = _send(uid)
    assert second["status"] == "duplicate"
    assert second["reason"] == "sent"
    assert len(fake_resend.calls) == 1
    assert fetch_one("SELECT COUNT(*) AS n FROM email_sends")["n"] == 1


def test_concurrent_claims_send_once(fake_resend, configured):
    uid = _user()
    results: list[dict[str, Any]] = []
    threads = [threading.Thread(target=lambda: results.append(_send(uid))) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r["status"] for r in results).count("sent") == 1
    assert len(fake_resend.calls) == 1


def test_failed_send_is_retried_up_to_cap(fake_resend, configured):
    uid = _user()
    fake_resend.fail_with = RuntimeError("resend down")
    first = _send(uid)
    assert first["status"] == "failed" and "resend down" in first["error"]
    assert fetch_one("SELECT status, attempts FROM email_sends")["status"] == "failed"

    fake_resend.fail_with = None
    retry = _send(uid)
    assert retry["status"] == "sent"
    assert retry["email_send_id"] == first["email_send_id"]
    row = fetch_one("SELECT status, attempts, error FROM email_sends")
    assert row == {"status": "sent", "attempts": 2, "error": None}
    # Same idempotency key on the retry, so Resend itself dedupes within 24 hours.
    assert fake_resend.calls[0][1] == fake_resend.calls[1][1]


def test_failed_send_stops_after_max_attempts(fake_resend, configured):
    uid = _user()
    fake_resend.fail_with = RuntimeError("bad address")
    for _ in range(email_service.MAX_SEND_ATTEMPTS):
        assert _send(uid)["status"] == "failed"
    assert _send(uid)["status"] == "duplicate"
    assert len(fake_resend.calls) == email_service.MAX_SEND_ATTEMPTS


def test_stuck_claim_is_never_resent(fake_resend, configured):
    uid = _user()
    execute(
        "INSERT INTO email_sends (user_id, to_email, template, dedupe_key, status) VALUES (?, 'dev@example.com', 'welcome', ?, 'claimed')",
        (uid, f"welcome:{uid}"),
    )
    assert _send(uid)["status"] == "duplicate"
    assert fake_resend.calls == []


# ---------------------------------------------------------------------------
# Dry run, gating and refusals
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing(fake_resend):
    uid = _user()
    result = _send(uid, dry_run=True)
    assert result["status"] == "dry_run"
    assert fake_resend.calls == []
    assert fetch_all("SELECT id FROM email_sends") == []


def test_dry_run_reports_duplicate(fake_resend, configured):
    uid = _user()
    _send(uid)
    assert _send(uid, dry_run=True)["status"] == "duplicate"


def test_lifecycle_refused_while_flag_off(fake_resend, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "founder@example.com")
    uid = _user()
    result = _send(uid)
    assert result == {"status": "skipped", "email_send_id": None, "provider_id": None,
                      "reason": "flag_off:lifecycle_emails", "error": None}
    assert fake_resend.calls == [] and fetch_all("SELECT id FROM email_sends") == []


def test_feedback_ack_gated_by_its_own_flag(fake_resend, configured):
    execute("UPDATE feature_flags SET enabled = 0 WHERE key = 'feedback_ack_emails'")
    uid = _user()
    result = _send(uid, template="feedback_ack", stream="feedback", dedupe_key="feedback_ack:platform:1")
    assert result["reason"] == "flag_off:feedback_ack_emails"
    assert fake_resend.calls == []


def test_refused_without_reply_to(fake_resend, configured, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "")
    assert _send(_user())["reason"] == "reply_to_unset"
    assert fake_resend.calls == []


def test_refused_without_resend_key(fake_resend, configured, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "")
    assert _send(_user())["reason"] == "resend_not_configured"


def test_unsubscribed_and_suppressed_users_skipped(fake_resend, configured):
    unsub = _user("a@example.com")
    supp = _user("b@example.com")
    execute("UPDATE users SET email_unsubscribed_at = datetime('now') WHERE id = ?", (unsub,))
    execute("UPDATE users SET email_suppressed_at = datetime('now'), email_suppressed_reason = 'bounced' WHERE id = ?", (supp,))
    assert _send(unsub)["reason"] == "unsubscribed"
    assert _send(supp)["reason"] == "suppressed"
    assert _send(unsub, dry_run=True)["reason"] == "unsubscribed"
    assert fake_resend.calls == []


def test_feedback_reply_ignores_unsubscribe_but_not_suppression(fake_resend, configured):
    unsub = _user("a@example.com")
    supp = _user("b@example.com")
    execute("UPDATE users SET email_unsubscribed_at = datetime('now') WHERE id = ?", (unsub,))
    execute("UPDATE users SET email_suppressed_at = datetime('now'), email_suppressed_reason = 'bounced' WHERE id = ?", (supp,))
    reply = {"template": "feedback_reply", "stream": "feedback"}
    assert _send(unsub, dedupe_key="feedback_reply:platform:1:a", **reply)["status"] == "sent"
    assert _send(supp, dedupe_key="feedback_reply:platform:2:b", **reply)["reason"] == "suppressed"
    # The instant acknowledgment is not a reply: it still honors the unsubscribe.
    ack = _send(unsub, template="feedback_ack", stream="feedback", dedupe_key="feedback_ack:platform:1")
    assert ack["reason"] == "unsubscribed"
    assert len(fake_resend.calls) == 1


def test_transactional_stream_ignores_unsubscribe_and_uses_auth_sender(fake_resend, configured):
    uid = _user()
    execute("UPDATE users SET email_unsubscribed_at = datetime('now') WHERE id = ?", (uid,))
    result = _send(uid, template="verify_reminder", stream="transactional", dedupe_key=f"verify_reminder:{uid}")
    assert result["status"] == "sent"
    params, _ = fake_resend.calls[0]
    assert params["from"] == "Kodwai <noreply@kodwai.com>"
    assert "headers" not in params and "reply_to" not in params


def test_explicit_reply_to_and_extra_headers(fake_resend, configured):
    uid = _user()
    _send(uid, template="feedback_reply", stream="feedback", dedupe_key="feedback_reply:platform:1:abc",
          reply_to="other@example.com", headers={"X-Entity-Ref-ID": "fb-1"})
    params, _ = fake_resend.calls[0]
    assert params["reply_to"] == "other@example.com"
    assert params["headers"]["X-Entity-Ref-ID"] == "fb-1"
    assert "List-Unsubscribe" in params["headers"]


def test_founder_notification_without_user_has_no_unsubscribe_header(fake_resend, configured):
    result = _send(None, to="founder@example.com", template="feedback_ack_founder", stream="feedback",
                   dedupe_key="feedback_ack_founder:platform:1")
    assert result["status"] == "sent"
    assert "List-Unsubscribe" not in fake_resend.calls[0][0].get("headers", {})


def test_long_dedupe_key_gets_hashed_idempotency_key(fake_resend, configured):
    key = "x" * 300
    _send(_user(), dedupe_key=key)
    assert len(fake_resend.calls[0][1]["idempotency_key"]) == 64


def test_bad_stream_raises():
    with pytest.raises(ValueError):
        _send("u1", stream="marketing")


def test_email_sent_event_captured(fake_resend, configured, monkeypatch):
    captured: list[tuple] = []
    monkeypatch.setattr(email_service, "capture", lambda *a, **k: captured.append(a))
    uid = _user()
    _send(uid)
    assert captured and captured[0][0] == uid and captured[0][1] == "email_sent"


# ---------------------------------------------------------------------------
# Unsubscribe tokens and helpers
# ---------------------------------------------------------------------------

def test_unsubscribe_token_round_trip():
    tok = unsubscribe_token("user-123")
    assert len(tok) == 32
    assert verify_unsubscribe_token("user-123", tok) is True
    assert verify_unsubscribe_token("user-124", tok) is False
    assert verify_unsubscribe_token("user-123", tok[:-1] + ("0" if tok[-1] != "0" else "1")) is False
    assert verify_unsubscribe_token("user-123", "") is False


def test_unsubscribe_token_depends_on_secret(monkeypatch):
    tok = unsubscribe_token("user-123")
    monkeypatch.setattr("app.core.config.settings.UNSUBSCRIBE_SECRET", "rotated")
    assert verify_unsubscribe_token("user-123", tok) is False
    monkeypatch.setattr("app.core.config.settings.UNSUBSCRIBE_SECRET", "")
    assert verify_unsubscribe_token("user-123", tok) is False
    with pytest.raises(RuntimeError):
        unsubscribe_token("user-123")


def test_unsubscribe_url_shape():
    url = unsubscribe_url("abc")
    assert url == f"https://api.kodwai.com/api/email/unsubscribe?u=abc&t={unsubscribe_token('abc')}"


def test_mask_email():
    assert mask_email("jane@example.com") == "j***@example.com"
    assert mask_email("") == "***"
    assert mask_email(None) == "***"


def test_with_utm_keeps_existing_params():
    url = with_utm("https://www.kodwai.com/challenges/x?ref=a&utm_source=old", "welcome")
    assert url == "https://www.kodwai.com/challenges/x?ref=a&utm_source=email&utm_medium=lifecycle&utm_campaign=welcome"


# ---------------------------------------------------------------------------
# Existing templates: escaping and configured sender
# ---------------------------------------------------------------------------

def test_invitation_email_escapes_names(fake_resend, monkeypatch):
    email_service._send_invitation_email("to@example.com", "<b>Evil Org</b>", "<script>x</script>", "inv1", "http://c")
    params, _ = fake_resend.calls[0]
    assert "<script>" not in params["html"] and "&lt;script&gt;" in params["html"]
    assert "<b>Evil Org</b>" not in params["html"]
    assert params["from"] == "Kodwai <noreply@kodwai.com>"


def test_session_invitation_email_escapes_names(fake_resend):
    email_service._send_session_invitation_email("to@example.com", "<img src=x>", "<i>Proj</i>", "s1", "tok", 60, "http://a")
    html = fake_resend.calls[0][0]["html"]
    assert "<img src=x>" not in html and "<img" not in html and "&lt;img" in html
    assert "<i>Proj</i>" not in html
