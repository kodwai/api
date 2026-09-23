"""Lifecycle runner: segment windows and skip rules, exclusions, caps, idempotency, refusals,
the admin routes, and the copy rules every template must follow. Resend is mocked."""
from __future__ import annotations

import json
import re
from typing import Any

import pytest

from app.core.database import execute, fetch_all, fetch_one
from app.core.security import create_access_token
from app.services import email_templates, lifecycle
from app.services.automation_tokens import mint_token
from tests.growth_factories import (
    FakeResend,
    breakdown,
    cli_login,
    configure_lifecycle,
    install_fake_resend,
    ledger_row,
    make_submission,
    make_user,
    welcomed,
)


@pytest.fixture
def fake_resend(monkeypatch) -> FakeResend:
    return install_fake_resend(monkeypatch)


@pytest.fixture
def configured(monkeypatch) -> None:
    configure_lifecycle(monkeypatch)


def _plan(**kwargs: Any) -> dict[str, Any]:
    return lifecycle.run(dry_run=True, **kwargs)


def _for(result: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
    return [item for item in result["items"] if item["user_id"] == user_id]


def _template_for(user_id: str, **kwargs: Any) -> str | None:
    """The template planned for this user (status dry_run), or None."""
    items = [i for i in _for(_plan(**kwargs), user_id) if i["status"] == "dry_run"]
    assert len(items) <= 1, items
    return items[0]["template"] if items else None


# ---------------------------------------------------------------------------
# Segment windows and skip rules
# ---------------------------------------------------------------------------

def test_welcome_backstop_within_72h_without_a_submission():
    fresh = make_user("fresh@example.com", hours_ago=10)
    started = make_user("started@example.com", hours_ago=10)
    make_submission(started, status="in_progress", started_hours_ago=30, scored_hours_ago=None)
    old = make_user("old@example.com", hours_ago=100)

    assert _template_for(fresh) == "welcome"
    assert _template_for(started) is None
    assert _template_for(old) is None


def test_d1_start_window_and_cli_login_exit():
    in_window = make_user("d1@example.com", hours_ago=30)
    welcomed(in_window, 29)
    expired = make_user("late@example.com", hours_ago=80)
    welcomed(expired, 79)
    logged_in = make_user("cli@example.com", hours_ago=30)
    welcomed(logged_in, 29)
    cli_login(logged_in, hours_ago=26)

    assert _template_for(in_window) == "d1_start"
    assert _template_for(expired) is None
    assert _template_for(logged_in) is None


def test_verify_reminder_only_for_unverified_signups_in_window():
    due = make_user("unverified@example.com", hours_ago=30, verified=False, token="tok123")
    too_early = make_user("early@example.com", hours_ago=10, verified=False, token="tok456")
    verified = make_user("verified@example.com", hours_ago=30)
    welcomed(verified, 29)

    result = _plan()
    due_items = _for(result, due)
    assert [i["template"] for i in due_items] == ["verify_reminder"]
    assert _for(result, too_early) == []
    assert all(i["template"] != "verify_reminder" for i in _for(result, verified))

    preview = lifecycle.preview("verify_reminder", due)
    assert "/verify?token=tok123" in preview["text"]
    assert "Unsubscribe" not in preview["text"]  # transactional: no unsubscribe footer


def test_d3_first_submit_needs_cli_login_and_no_submission():
    due = make_user("d3@example.com", hours_ago=4 * 24)
    welcomed(due, 95)
    cli_login(due, hours_ago=80)
    submitted = make_user("d3sub@example.com", hours_ago=4 * 24)
    welcomed(submitted, 95)
    cli_login(submitted, hours_ago=80)
    make_submission(submitted, status="error", started_hours_ago=79, scored_hours_ago=None)
    stale = make_user("d3old@example.com", hours_ago=150)  # past the 6-day window, before day 7
    welcomed(stale, 149)
    cli_login(stale, hours_ago=140)

    assert _template_for(due) == "d3_first_submit"
    assert _template_for(submitted) is None
    assert _template_for(stale) is None


def test_stalled_submission_window_and_scored_exit():
    stalled = make_user("stalled@example.com", hours_ago=5 * 24)
    welcomed(stalled, 110)
    make_submission(stalled, status="in_progress", started_hours_ago=72, scored_hours_ago=None)
    fresh = make_user("fresh@example.com", hours_ago=5 * 24)
    welcomed(fresh, 110)
    make_submission(fresh, status="in_progress", started_hours_ago=30, scored_hours_ago=None)
    stale = make_user("stale@example.com", hours_ago=12 * 24)
    welcomed(stale, 280)
    make_submission(stale, status="in_progress", started_hours_ago=8 * 24, scored_hours_ago=None)
    has_score = make_user("scored@example.com", hours_ago=12 * 24)
    welcomed(has_score, 280)
    make_submission(has_score, status="scored", started_hours_ago=200, scored_hours_ago=199)
    make_submission(has_score, status="in_progress", started_hours_ago=72, scored_hours_ago=None)

    assert _template_for(stalled) == "stalled_submission"
    assert _template_for(fresh) is None
    assert _template_for(stale) is None
    assert _template_for(has_score) is None

    preview = lifecycle.preview("stalled_submission", stalled)
    assert "npx @kodwai/cli submit" in preview["text"]
    assert "3 days ago" in preview["text"]
    assert "kodwai-bookshelf-rest-api" in preview["text"]


def test_first_score_backstop_is_a_milestone_exempt_from_caps_and_activity():
    user = make_user("first@example.com", hours_ago=4 * 24)
    welcomed(user, 2)  # a lifecycle send 2 h ago: the daily cap would block a drip step
    make_submission(user, started_hours_ago=6, scored_hours_ago=5)  # recent activity too
    ineligible = make_user("inelig@example.com", hours_ago=4 * 24)
    welcomed(ineligible, 90)
    make_submission(ineligible, started_hours_ago=30, scored_hours_ago=29, eligible=0)
    old_score = make_user("oldscore@example.com", hours_ago=9 * 24)
    welcomed(old_score, 200)
    make_submission(old_score, started_hours_ago=5 * 24, scored_hours_ago=4 * 24)

    assert _template_for(user) == "first_score"
    assert all(i["template"] != "first_score" for i in _for(_plan(), ineligible))
    assert all(i["template"] != "first_score" for i in _for(_plan(), old_score))


def test_d7_scored_offers_an_unattempted_harder_challenge():
    user = make_user("d7s@example.com", hours_ago=8 * 24)
    welcomed(user, 180)
    make_submission(user, started_hours_ago=6 * 24, scored_hours_ago=6 * 24 - 1,
                    score_breakdown=breakdown(direction=20, outcome=33, lift=14))
    second = make_user("d7s2@example.com", hours_ago=8 * 24)
    welcomed(second, 180)
    make_submission(second, started_hours_ago=6 * 24, scored_hours_ago=6 * 24 - 1)
    make_submission(second, slug="secrets-vault-with-envelope-encryption",
                    started_hours_ago=5 * 24, scored_hours_ago=5 * 24 - 1)

    assert _template_for(user) == "d7_scored"
    assert _template_for(second) is None

    text = lifecycle.preview("d7_scored", user)["text"]
    medium = {r["slug"] for r in fetch_all("SELECT slug FROM challenges WHERE difficulty = 'medium'")}
    linked = re.search(r"/dev/challenges/([a-z0-9-]+)\?", text)
    assert linked and linked.group(1) in medium
    assert "Most of the points you missed were in Direction" in text
    assert "72/100" in text


def test_d7_not_scored_window():
    due = make_user("d7n@example.com", hours_ago=8 * 24)
    welcomed(due, 180)
    late = make_user("d7late@example.com", hours_ago=11 * 24)
    welcomed(late, 250)

    assert _template_for(due) == "d7_not_scored"
    assert _template_for(late) is None


def test_reengage_at_most_two_sends_14_days_apart():
    user = make_user("back@example.com", hours_ago=90 * 24)
    welcomed(user, 89 * 24)
    make_submission(user, started_hours_ago=40 * 24, scored_hours_ago=40 * 24 - 1)
    # Seeded challenges were created "now", i.e. after the last run 40 days ago.
    assert _template_for(user) == "reengage"
    assert _for(_plan(), user)[0]["reason"].endswith("send 1")

    ledger_row(user, "reengage", hours_ago=5 * 24, dedupe_key=f"reengage:{user}:1")
    assert _template_for(user) is None  # second send waits 14 days

    execute("UPDATE email_sends SET created_at = datetime('now', '-15 days') WHERE dedupe_key = ?", (f"reengage:{user}:1",))
    assert _template_for(user) == "reengage"

    ledger_row(user, "reengage", hours_ago=15 * 24, dedupe_key=f"reengage:{user}:2")
    assert _template_for(user) is None  # sunset after two


def test_reengage_skips_users_active_in_the_last_30_days():
    user = make_user("active@example.com", hours_ago=90 * 24)
    welcomed(user, 89 * 24)
    make_submission(user, started_hours_ago=10 * 24, scored_hours_ago=10 * 24 - 1)
    assert _template_for(user) is None


# ---------------------------------------------------------------------------
# Exclusions, caps, one per run, limit
# ---------------------------------------------------------------------------

def test_base_filter_excludes_demo_internal_banned_unsubscribed_suppressed_and_company(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.INTERNAL_EMAILS", "Founder@Example.com, qa@example.com")
    control = make_user("real@example.com", hours_ago=10)
    excluded = [
        make_user("seeded@demo.kodwai.dev", hours_ago=10),
        make_user("flagged@example.com", hours_ago=10, is_demo=1),
        make_user("founder@example.com", hours_ago=10),
        make_user("banned@example.com", hours_ago=10, banned=1),
        make_user("unsub@example.com", hours_ago=10, unsubscribed=True),
        make_user("bounced@example.com", hours_ago=10, suppressed=True),
        make_user("company@example.com", hours_ago=10, user_type="company"),
    ]
    result = _plan()
    planned = {i["user_id"] for i in result["items"]}
    assert control in planned
    assert planned.isdisjoint(excluded)


def test_daily_cap_weekly_cap_and_recent_activity_skip():
    capped_daily = make_user("daily@example.com", hours_ago=30)
    welcomed(capped_daily, 2)
    capped_weekly = make_user("weekly@example.com", hours_ago=8 * 24)
    welcomed(capped_weekly, 7 * 24 - 1)
    ledger_row(capped_weekly, "d1_start", hours_ago=5 * 24)
    ledger_row(capped_weekly, "d3_first_submit", hours_ago=3 * 24)
    active = make_user("active@example.com", hours_ago=8 * 24)
    welcomed(active, 180)
    make_submission(active, status="in_progress", started_hours_ago=2, scored_hours_ago=None)

    result = _plan()
    assert [(i["template"], i["status"], i["reason"]) for i in _for(result, capped_daily)] == [
        ("d1_start", "skipped", "cap_daily")]
    assert [(i["template"], i["status"], i["reason"]) for i in _for(result, capped_weekly)] == [
        ("d7_not_scored", "skipped", "cap_weekly")]
    assert [(i["template"], i["status"], i["reason"]) for i in _for(result, active)] == [
        ("d7_not_scored", "skipped", "recent_activity")]


def test_one_email_per_user_per_run_highest_priority_wins():
    user = make_user("both@example.com", hours_ago=30)  # in both the welcome and d1_start windows
    assert [i["template"] for i in _for(_plan(), user)] == ["welcome"]


def test_limit_caps_planned_emails():
    for n in range(3):
        make_user(f"u{n}@example.com", hours_ago=10)
    result = _plan(limit=2)
    assert [i["status"] for i in result["items"]] == ["dry_run", "dry_run"]
    assert result["limit_reached"] is True


def test_templates_filter_and_validation():
    user = make_user("d7n@example.com", hours_ago=8 * 24)
    welcomed(user, 180)
    make_user("fresh@example.com", hours_ago=10)
    result = _plan(templates=["d7_not_scored"])
    assert {i["template"] for i in result["items"]} == {"d7_not_scored"}
    with pytest.raises(ValueError):
        _plan(templates=["nope"])
    with pytest.raises(ValueError):
        _plan(templates=["news"])  # manual only, never scheduled


# ---------------------------------------------------------------------------
# Real runs: idempotency and refusals
# ---------------------------------------------------------------------------

def test_real_run_sends_once_across_repeated_runs(fake_resend, configured):
    user = make_user("d1@example.com", hours_ago=30)
    welcomed(user, 29)

    first = lifecycle.run(dry_run=False, run_id="run-1")
    assert first["refused_reason"] is None
    assert [(i["template"], i["status"]) for i in _for(first, user)] == [("d1_start", "sent")]

    second = lifecycle.run(dry_run=False, run_id="run-2")
    assert _for(second, user) == []
    assert len(fake_resend.calls) == 1

    rows = fetch_all("SELECT template, status, run_id, dedupe_key FROM email_sends WHERE user_id = ? AND template = 'd1_start'", (user,))
    assert rows == [{"template": "d1_start", "status": "sent", "run_id": "run-1", "dedupe_key": f"d1_start:{user}"}]

    params, options = fake_resend.calls[0]
    assert options == {"idempotency_key": f"d1_start:{user}"}
    assert params["from"] == '"Hakan from Kodwai" <hi@updates.kodwai.com>'
    assert params["reply_to"] == "founder@example.com"
    assert params["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert params["text"] and params["html"]
    assert params["subject"] == "The one command that starts a kodwai challenge"


def test_real_run_refused_while_flag_off(fake_resend, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "founder@example.com")
    user = make_user("fresh@example.com", hours_ago=10)

    result = lifecycle.run(dry_run=False)
    assert result["refused_reason"] == "flag_off:lifecycle_emails"
    assert result["dry_run"] is False
    assert [i["status"] for i in _for(result, user)] == ["refused"]
    assert fake_resend.calls == []
    assert fetch_one("SELECT COUNT(*) AS n FROM email_sends")["n"] == 0


def test_real_run_refused_without_reply_to(fake_resend, configured, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "")
    make_user("fresh@example.com", hours_ago=10)
    result = lifecycle.run(dry_run=False)
    assert result["refused_reason"] == "reply_to_unset"
    assert fake_resend.calls == []


def test_real_run_refused_without_lifecycle_sender(fake_resend, configured, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.EMAIL_FROM_LIFECYCLE", "")
    make_user("fresh@example.com", hours_ago=10)
    assert lifecycle.run(dry_run=False)["refused_reason"] == "email_from_lifecycle_unset"
    assert fake_resend.calls == []


def test_dry_run_is_always_allowed_and_writes_nothing():
    make_user("fresh@example.com", hours_ago=10)
    result = _plan()
    assert result["refused_reason"] is None and result["dry_run"] is True
    assert result["counts"] == {"dry_run": 1}
    assert fetch_one("SELECT COUNT(*) AS n FROM email_sends")["n"] == 0


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@pytest.fixture
def superadmin() -> str:
    return make_user("root@example.com", user_type="company", superadmin=1)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_run_route_requires_the_lifecycle_scope(client, superadmin):
    assert client.post("/api/admin/lifecycle/run", json={}).status_code == 401
    wrong = mint_token("reader", ["email:read"], superadmin, 90)["token"]
    assert client.post("/api/admin/lifecycle/run", json={}, headers=_bearer(wrong)).status_code == 403

    right = mint_token("routine", ["lifecycle:run"], superadmin, 90)["token"]
    make_user("fresh@example.com", hours_ago=10)
    resp = client.post("/api/admin/lifecycle/run", json={}, headers=_bearer(right))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True and body["refused_reason"] is None
    assert body["items"][0]["masked_email"] == "f***@example.com"
    assert set(body["items"][0]) >= {"user_id", "masked_email", "template", "reason", "status"}


def test_real_run_route_is_refused_and_audited(client, superadmin):
    headers = _bearer(create_access_token({"sub": superadmin, "type": "admin"}))
    make_user("fresh@example.com", hours_ago=10)
    resp = client.post("/api/admin/lifecycle/run", json={"dry_run": False, "run_id": "growth-daily-1"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["refused_reason"] == "flag_off:lifecycle_emails"
    audit = fetch_one("SELECT * FROM admin_audit_log WHERE action = 'lifecycle_run'")
    assert audit["admin_user_id"] == superadmin and audit["entity_id"] == "growth-daily-1"
    assert json.loads(audit["details"])["refused_reason"] == "flag_off:lifecycle_emails"


def test_run_route_rejects_unknown_templates_and_bad_run_ids(client, superadmin):
    headers = _bearer(create_access_token({"sub": superadmin, "type": "admin"}))
    assert client.post("/api/admin/lifecycle/run", json={"templates": ["nope"]}, headers=headers).status_code == 400
    assert client.post("/api/admin/lifecycle/run", json={"run_id": "bad id!"}, headers=headers).status_code == 422
    assert client.post("/api/admin/lifecycle/run", json={"limit": 0}, headers=headers).status_code == 422


def test_preview_route(client, superadmin):
    token = mint_token("routine", ["lifecycle:run"], superadmin, 90)["token"]
    user = make_user("grace@example.com", name="Grace Hopper")

    resp = client.get("/api/admin/lifecycle/preview", params={"template": "welcome", "user_id": user}, headers=_bearer(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["template"] == "welcome"
    assert body["subject"] == "Your first kodwai challenge is one command away"
    assert body["text"].startswith("Hi Grace,")
    assert "npx @kodwai/cli challenge bookshelf-rest-api" in body["text"]
    assert "npx @kodwai/cli challenge bookshelf-rest-api" in body["html"]
    assert body["html"].startswith("<!doctype html>")

    sample = client.get("/api/admin/lifecycle/preview", params={"template": "news"}, headers=_bearer(token))
    assert sample.status_code == 200
    assert client.get("/api/admin/lifecycle/preview", params={"template": "nope"}, headers=_bearer(token)).status_code == 400
    missing = client.get("/api/admin/lifecycle/preview", params={"template": "welcome", "user_id": "nobody"}, headers=_bearer(token))
    assert missing.status_code == 404


def test_email_sends_route(client, superadmin):
    token = mint_token("reader", ["email:read"], superadmin, 90)["token"]
    user = make_user("jane@example.com")
    ledger_row(user, "welcome", hours_ago=1, to_email="jane@example.com")
    ledger_row(user, "d1_start", hours_ago=24 * 10, to_email="jane@example.com")

    resp = client.get("/api/admin/email-sends", headers=_bearer(token))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [i["template"] for i in items] == ["welcome", "d1_start"]
    assert items[0]["masked_email"] == "j***@example.com"
    assert "to_email" not in items[0]

    recent = client.get("/api/admin/email-sends", params={"since": "2000-01-01", "template": "welcome"}, headers=_bearer(token))
    assert [i["template"] for i in recent.json()["items"]] == ["welcome"]
    assert client.get("/api/admin/email-sends", params={"since": "yesterday"}, headers=_bearer(token)).status_code == 422
    no_scope = mint_token("routine", ["lifecycle:run"], superadmin, 90)["token"]
    assert client.get("/api/admin/email-sends", headers=_bearer(no_scope)).status_code == 403


# ---------------------------------------------------------------------------
# Copy rules
# ---------------------------------------------------------------------------

_DASHES = ("—", "–", "―", " -- ")
_URL = re.compile(r"https?://[^\s\"'<>]+")


@pytest.mark.parametrize("template", sorted(lifecycle.TEMPLATES))
def test_every_template_follows_the_copy_rules(template, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.COMPANY_POSTAL_ADDRESS", "1 Example Street, Istanbul")
    email = lifecycle.preview(template)

    for part in (email["subject"], email["text"], email["html"]):
        for dash in _DASHES:
            assert dash not in part, f"{template} contains {dash!r}"
        assert "KodWai" not in part and "Kodwai AI" not in part
        assert "five" not in part.lower() and "5 dimensions" not in part
        assert not re.search(r"\bEge\b", part), f"{template} uses the founder's old first name"
    assert "\n\nHakan\n" in email["text"]
    assert "You're getting this because" in email["text"]
    assert "1 Example Street, Istanbul" in email["text"]

    links = _URL.findall(email["text"])
    unsubscribe = [u for u in links if "/api/email/unsubscribe" in u]
    product = [u for u in links if "/api/email/unsubscribe" not in u]
    assert len(product) <= 1, f"{template} has more than one link CTA: {product}"
    for url in product:
        assert "utm_source=email" in url and "utm_medium=lifecycle" in url and f"utm_campaign={template}" in url
    if template == "verify_reminder":
        assert unsubscribe == []
    else:
        assert len(unsubscribe) == 1


def test_html_part_escapes_user_values():
    email = email_templates.welcome(user_id="u1", name="<script>x</script>", starter_slug="bookshelf-rest-api")
    assert "<script>" not in email.html and "&lt;script&gt;" in email.html


def test_welcome_and_verify_email_sign_as_hakan_never_ege():
    welcome = email_templates.welcome(user_id="u1", name="Jane", starter_slug="bookshelf-rest-api")
    verify = email_templates.verify_email(name="Jane Doe", verify_url="https://app.kodwai.com/verify?t=x")
    assert "I'm Hakan, co-founder of kodwai." in welcome.text
    for email in (welcome, verify):
        assert "\n\nHakan\n" in email.text
        for part in (email.subject, email.text, email.html):
            assert "Ege" not in part


def test_score_is_three_axes_and_rounds_like_the_app():
    assert list(email_templates.SCORE_AXES) == ["direction", "outcome", "lift"]
    assert email_templates.format_score(72.5) == "73"
    assert email_templates.format_score(72.4) == "72"
    assert "three axes: Direction, Outcome and Lift" in lifecycle.preview("welcome")["text"]
