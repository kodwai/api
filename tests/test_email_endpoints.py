"""Public email endpoints: unsubscribe (GET page, POST one-click) and the svix-signed Resend webhook."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from app.core.database import execute, fetch_one
from app.services import lifecycle
from app.services.email_service import unsubscribe_token
from tests.growth_factories import ledger_row, make_user

WEBHOOK_SECRET = "whsec_" + base64.b64encode(b"kodwai-test-webhook-secret-bytes").decode()


def _unsubscribed_at(user_id: str) -> str | None:
    return fetch_one("SELECT email_unsubscribed_at FROM users WHERE id = ?", (user_id,))["email_unsubscribed_at"]


# ---------------------------------------------------------------------------
# Unsubscribe
# ---------------------------------------------------------------------------

def test_unsubscribe_get_only_shows_a_confirm_button(client):
    # Mail scanners pre-open GET links, so a GET must not unsubscribe.
    user = make_user("dev@example.com", hours_ago=10)
    resp = client.get("/api/email/unsubscribe", params={"u": user, "t": unsubscribe_token(user)})
    assert resp.status_code == 200
    assert '<form method="post" action="/api/email/unsubscribe/confirm?' in resp.text
    assert "—" not in resp.text and "–" not in resp.text
    assert 'name="robots" content="noindex"' in resp.text
    assert _unsubscribed_at(user) is None


def test_unsubscribe_confirm_sets_timestamp_and_confirms(client):
    user = make_user("dev@example.com", hours_ago=10)
    resp = client.post("/api/email/unsubscribe/confirm", params={"u": user, "t": unsubscribe_token(user)})
    assert resp.status_code == 200
    assert "You're unsubscribed" in resp.text.replace("&#x27;", "'")
    assert "—" not in resp.text and "–" not in resp.text
    assert 'name="robots" content="noindex"' in resp.text
    assert _unsubscribed_at(user) is not None
    # The runner no longer plans anything for this user.
    assert all(i["user_id"] != user for i in lifecycle.run(dry_run=True)["items"])


def test_unsubscribe_page_rejects_a_bad_token(client):
    user = make_user("dev@example.com")
    resp = client.get("/api/email/unsubscribe", params={"u": user, "t": "0" * 32})
    assert resp.status_code == 400
    assert "doesn't look right" in resp.text.replace("&#x27;", "'")
    assert _unsubscribed_at(user) is None
    assert client.get("/api/email/unsubscribe").status_code == 400
    assert client.post("/api/email/unsubscribe/confirm", params={"u": user, "t": "0" * 32}).status_code == 400
    assert _unsubscribed_at(user) is None


def test_one_click_post_returns_empty_200_and_keeps_the_first_timestamp(client):
    user = make_user("dev@example.com")
    params = {"u": user, "t": unsubscribe_token(user)}
    resp = client.post("/api/email/unsubscribe", params=params, content="List-Unsubscribe=One-Click",
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert resp.status_code == 200 and resp.content == b""
    first = _unsubscribed_at(user)
    assert first is not None

    execute("UPDATE users SET email_unsubscribed_at = '2026-01-01 00:00:00' WHERE id = ?", (user,))
    assert client.post("/api/email/unsubscribe", params=params).status_code == 200
    assert _unsubscribed_at(user) == "2026-01-01 00:00:00"


def test_one_click_post_rejects_a_bad_token(client):
    user = make_user("dev@example.com")
    assert client.post("/api/email/unsubscribe", params={"u": user, "t": "nope"}).status_code == 400
    assert _unsubscribed_at(user) is None


# ---------------------------------------------------------------------------
# Resend webhook
# ---------------------------------------------------------------------------

def _signed(payload: dict, *, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> tuple[str, dict[str, str]]:
    body = json.dumps(payload)
    msg_id = "msg_test_1"
    ts = str(timestamp if timestamp is not None else int(time.time()))
    key = base64.b64decode(secret.removeprefix("whsec_"))
    sig = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.{body}".encode(), hashlib.sha256).digest()).decode()
    return body, {"svix-id": msg_id, "svix-timestamp": ts, "svix-signature": f"v1,{sig}", "Content-Type": "application/json"}


@pytest.fixture
def webhook_secret(monkeypatch) -> str:
    monkeypatch.setattr("app.core.config.settings.RESEND_WEBHOOK_SECRET", WEBHOOK_SECRET)
    return WEBHOOK_SECRET


def _event(event_type: str, email_id: str, to: str = "dev@example.com", **data) -> dict:
    return {"type": event_type, "created_at": "2026-09-22T10:00:00.000Z",
            "data": {"email_id": email_id, "to": [to], "subject": "Hi", **data}}


def _user_state(user_id: str) -> dict:
    return fetch_one("SELECT email_suppressed_at, email_suppressed_reason FROM users WHERE id = ?", (user_id,))


def _row(row_id: str) -> dict:
    return fetch_one("SELECT status, error, attempts, meta FROM email_sends WHERE id = ?", (row_id,))


def test_webhook_refuses_when_the_secret_is_not_configured(client):
    body, headers = _signed(_event("email.delivered", "re_1"))
    assert client.post("/api/webhooks/resend", content=body, headers=headers).status_code == 503


def test_webhook_rejects_bad_and_stale_signatures(client, webhook_secret):
    user = make_user("dev@example.com")
    row = ledger_row(user, "welcome", provider_id="re_1", to_email="dev@example.com")
    event = _event("email.bounced", "re_1", bounce={"type": "Permanent", "subType": "General"})

    body, headers = _signed(event, secret="whsec_" + base64.b64encode(b"some-other-secret").decode())
    assert client.post("/api/webhooks/resend", content=body, headers=headers).status_code == 401

    body, headers = _signed(event, timestamp=int(time.time()) - 3600)
    assert client.post("/api/webhooks/resend", content=body, headers=headers).status_code == 401

    body, headers = _signed(event)
    tampered = body.replace("Permanent", "Temporary")
    assert client.post("/api/webhooks/resend", content=tampered, headers=headers).status_code == 401

    assert _user_state(user)["email_suppressed_at"] is None
    assert _row(row)["status"] == "sent"


def test_permanent_bounce_suppresses_and_is_never_retried(client, webhook_secret):
    user = make_user("dev@example.com", hours_ago=10)
    row = ledger_row(user, "welcome", provider_id="re_1", to_email="dev@example.com", dedupe_key=f"welcome:{user}")
    body, headers = _signed(_event("email.bounced", "re_1", bounce={
        "type": "Permanent", "subType": "Suppressed", "message": "Recipient has a history of hard bounces."}))

    resp = client.post("/api/webhooks/resend", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["suppressed"] is True
    state = _user_state(user)
    assert state["email_suppressed_at"] and state["email_suppressed_reason"] == "bounced:Suppressed"
    ledger = _row(row)
    assert ledger["status"] == "failed" and ledger["attempts"] >= 3 and "bounced" in ledger["error"]

    # Idempotent under svix retries.
    assert client.post("/api/webhooks/resend", content=body, headers=headers).status_code == 200


def test_temporary_bounce_marks_the_row_but_does_not_suppress(client, webhook_secret):
    user = make_user("dev@example.com")
    row = ledger_row(user, "d1_start", provider_id="re_2")
    body, headers = _signed(_event("email.bounced", "re_2", bounce={"type": "Temporary", "subType": "MailboxFull"}))
    assert client.post("/api/webhooks/resend", content=body, headers=headers).status_code == 200
    assert _user_state(user)["email_suppressed_at"] is None
    assert _row(row)["status"] == "failed"


def test_complaint_suppresses_and_keeps_the_row_sent(client, webhook_secret):
    user = make_user("dev@example.com")
    row = ledger_row(user, "d1_start", provider_id="re_3")
    body, headers = _signed(_event("email.complained", "re_3"))
    assert client.post("/api/webhooks/resend", content=body, headers=headers).status_code == 200
    assert _user_state(user)["email_suppressed_reason"] == "complained"
    assert _row(row)["status"] == "sent" and _row(row)["error"] == "complained"


def test_resend_suppression_event_suppresses(client, webhook_secret):
    user = make_user("dev@example.com")
    row = ledger_row(user, "welcome", provider_id="re_4")
    body, headers = _signed(_event("email.suppressed", "re_4", suppressed={"type": "OnAccountSuppressionList"}))
    assert client.post("/api/webhooks/resend", content=body, headers=headers).status_code == 200
    assert _user_state(user)["email_suppressed_reason"] == "suppressed:OnAccountSuppressionList"
    assert _row(row)["status"] == "failed" and _row(row)["attempts"] >= 3


def test_failed_event_stays_retryable_and_never_suppresses(client, webhook_secret):
    user = make_user("dev@example.com")
    row = ledger_row(user, "welcome", provider_id="re_5")
    body, headers = _signed(_event("email.failed", "re_5", failed={"reason": "reached_daily_quota"}))
    assert client.post("/api/webhooks/resend", content=body, headers=headers).status_code == 200
    assert _user_state(user)["email_suppressed_at"] is None
    ledger = _row(row)
    assert ledger["status"] == "failed" and ledger["attempts"] == 1 and "reached_daily_quota" in ledger["error"]


def test_delivered_event_stamps_the_row(client, webhook_secret):
    user = make_user("dev@example.com")
    row = ledger_row(user, "welcome", provider_id="re_6")
    body, headers = _signed(_event("email.delivered", "re_6"))
    assert client.post("/api/webhooks/resend", content=body, headers=headers).status_code == 200
    assert json.loads(_row(row)["meta"])["delivered_at"] == "2026-09-22T10:00:00.000Z"
    assert _row(row)["status"] == "sent"


def test_bounce_for_an_untracked_email_suppresses_by_address(client, webhook_secret):
    user = make_user("Dev@Example.com")
    body, headers = _signed(_event("email.bounced", "re_unknown", to="dev@example.com",
                                   bounce={"type": "Permanent", "subType": "General"}))
    resp = client.post("/api/webhooks/resend", content=body, headers=headers)
    assert resp.status_code == 200 and resp.json()["email_send_id"] is None
    assert _user_state(user)["email_suppressed_reason"] == "bounced:General"


def test_unhandled_event_types_are_acknowledged(client, webhook_secret):
    body, headers = _signed(_event("email.opened", "re_7"))
    resp = client.post("/api/webhooks/resend", content=body, headers=headers)
    assert resp.status_code == 200 and resp.json()["ignored"] is True
