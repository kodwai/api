"""Auth and scoring hooks for growth: welcome on verify / new GitHub account (flag-gated),
resend-verification rate limit, marketing consent, the /dev/welcome acquisition answer, the
first_score milestone, server-side PostHog events, and the 401 for GitHub-only password logins."""
from __future__ import annotations

from typing import Any

import pytest

from app.core.database import execute, fetch_all, fetch_one
from app.services import auth_service, email_service, lifecycle
from app.services.scoring import engine
from tests.growth_factories import (
    FakeResend,
    configure_lifecycle,
    install_fake_resend,
    make_submission,
    make_user,
)


@pytest.fixture
def fake_resend(monkeypatch) -> FakeResend:
    return install_fake_resend(monkeypatch)


@pytest.fixture
def configured(monkeypatch) -> None:
    configure_lifecycle(monkeypatch)


@pytest.fixture
def inline_sends(monkeypatch) -> None:
    """Run background sends inline so tests can assert on them."""
    monkeypatch.setattr(lifecycle, "_spawn", lambda fn, *args: fn(*args))
    monkeypatch.setattr(auth_service, "send_tracked_in_background",
                        lambda *args, **kwargs: email_service.send_tracked(*args, **kwargs))


@pytest.fixture
def events(monkeypatch) -> list[tuple[str | None, str, dict]]:
    """Capture server-side PostHog events from every module that emits them."""
    captured: list[tuple[str | None, str, dict]] = []

    def fake_capture(distinct_id: str | None, event: str, properties: dict | None = None) -> None:
        captured.append((distinct_id, event, properties or {}))

    monkeypatch.setattr("app.services.auth_service.capture", fake_capture)
    monkeypatch.setattr("app.routers.submissions.capture", fake_capture)
    monkeypatch.setattr("app.services.analytics_events.capture", fake_capture)
    monkeypatch.setattr("app.services.email_service.capture", fake_capture)
    return captured


def _signup(client, email: str = "dev@example.com", user_type: str = "developer", **extra: Any) -> dict:
    body = {"email": email, "password": "testpass123", "name": "Ada Lovelace", "user_type": user_type, **extra}
    if user_type == "company":
        body["organization_name"] = "Org"
    resp = client.post("/api/auth/signup", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client, email: str) -> dict[str, str]:
    execute("UPDATE users SET email_verified = 1 WHERE email = ?", (email,))
    resp = client.post("/api/auth/login", json={"email": email, "password": "testpass123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# GitHub-only accounts and password login
# ---------------------------------------------------------------------------

def test_admin_login_returns_401_for_a_github_only_account(client):
    make_user("gh@example.com", user_type="company", superadmin=1, password_hash="")
    resp = client.post("/api/admin/login", json={"email": "gh@example.com", "password": "anything"})
    assert resp.status_code == 401


def test_user_login_returns_401_for_a_github_only_account(client):
    make_user("gh@example.com", password_hash="")
    resp = client.post("/api/auth/login", json={"email": "gh@example.com", "password": "anything"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Signup: marketing consent and the signup_completed event
# ---------------------------------------------------------------------------

def test_signup_records_marketing_consent_only_when_checked(client, events):
    body = _signup(client, "yes@example.com", marketing_consent=True)
    _signup(client, "no@example.com")
    consent = {r["email"]: r["marketing_consent_at"] for r in fetch_all("SELECT email, marketing_consent_at FROM users")}
    assert consent["yes@example.com"] is not None
    assert consent["no@example.com"] is None

    uid = fetch_one("SELECT id FROM users WHERE email = 'yes@example.com'")["id"]
    assert body["user"]["id"] == uid
    assert (uid, "signup_completed", {"method": "email", "user_type": "developer"}) in events


# ---------------------------------------------------------------------------
# Resend verification
# ---------------------------------------------------------------------------

def test_resend_verification_is_always_204_and_rate_limited(client, fake_resend, inline_sends, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    _signup(client, "dev@example.com")
    assert fake_resend.to() == ["dev@example.com"]  # the signup verification email, now tracked
    params, _ = fake_resend.calls[0]
    assert params["from"] == "Kodwai <noreply@kodwai.com>"
    assert "/verify?token=" in params["text"]

    assert client.post("/api/auth/resend-verification", json={"email": "dev@example.com"}).status_code == 204
    assert len(fake_resend.calls) == 1  # within 10 minutes of the last one

    assert client.post("/api/auth/resend-verification", json={"email": "nobody@example.com"}).status_code == 204
    assert len(fake_resend.calls) == 1

    execute("UPDATE email_sends SET created_at = datetime('now', '-11 minutes')")
    assert client.post("/api/auth/resend-verification", json={"email": "dev@example.com"}).status_code == 204
    assert len(fake_resend.calls) == 2
    token = fetch_one("SELECT email_verification_token FROM users WHERE email = 'dev@example.com'")["email_verification_token"]
    assert f"/verify?token={token}" in fake_resend.calls[1][0]["text"]
    rows = fetch_all("SELECT template, stream FROM email_sends ORDER BY created_at")
    assert rows == [{"template": "verify_email", "stream": "transactional"}] * 2

    # Verified accounts get nothing.
    execute("UPDATE users SET email_verified = 1 WHERE email = 'dev@example.com'")
    execute("UPDATE email_sends SET created_at = datetime('now', '-11 minutes')")
    assert client.post("/api/auth/resend-verification", json={"email": "dev@example.com"}).status_code == 204
    assert len(fake_resend.calls) == 2


def test_resend_verification_is_204_even_for_a_malformed_email(client, fake_resend, inline_sends):
    assert client.post("/api/auth/resend-verification", json={"email": "not-an-email"}).status_code == 204
    assert fake_resend.calls == []


# ---------------------------------------------------------------------------
# Welcome on verify and on a new GitHub account
# ---------------------------------------------------------------------------

def _verify(client, email: str) -> None:
    token = fetch_one("SELECT email_verification_token FROM users WHERE email = ?", (email,))["email_verification_token"]
    assert client.get("/api/auth/verify-email", params={"token": token}).status_code == 200


def test_welcome_is_not_sent_while_the_flag_is_off(client, fake_resend, inline_sends, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "founder@example.com")
    _signup(client, "dev@example.com")
    _verify(client, "dev@example.com")
    assert [p["subject"] for p, _ in fake_resend.calls] == ["Verify your email for kodwai"]
    assert fetch_one("SELECT COUNT(*) AS n FROM email_sends WHERE template = 'welcome'")["n"] == 0


def test_welcome_is_not_sent_without_a_reply_to(client, fake_resend, inline_sends, configured, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "")
    _signup(client, "dev@example.com")
    _verify(client, "dev@example.com")
    assert fetch_one("SELECT COUNT(*) AS n FROM email_sends WHERE template = 'welcome'")["n"] == 0


def test_welcome_is_sent_once_on_verify_when_enabled(client, fake_resend, inline_sends, configured):
    _signup(client, "dev@example.com")
    _verify(client, "dev@example.com")
    welcome = [(p, o) for p, o in fake_resend.calls if p["subject"] == "Your first kodwai challenge is one command away"]
    assert len(welcome) == 1
    params, options = welcome[0]
    uid = fetch_one("SELECT id FROM users WHERE email = 'dev@example.com'")["id"]
    assert options == {"idempotency_key": f"welcome:{uid}"}
    assert params["from"] == '"Ege at Kodwai" <hi@updates.kodwai.com>'
    assert "List-Unsubscribe" in params["headers"]

    # The daily backstop sees it as sent.
    assert all(i["template"] != "welcome" for i in lifecycle.run(dry_run=True)["items"])
    assert lifecycle.send_event_email("welcome", uid)["status"] == "duplicate"


def test_welcome_skips_company_demo_and_internal_accounts(client, fake_resend, inline_sends, configured, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.INTERNAL_EMAILS", "team@example.com")
    _signup(client, "company@example.com", user_type="company")
    _signup(client, "someone@demo.kodwai.dev")
    _signup(client, "team@example.com")
    for email in ("company@example.com", "someone@demo.kodwai.dev", "team@example.com"):
        _verify(client, email)
    assert fetch_one("SELECT COUNT(*) AS n FROM email_sends WHERE template = 'welcome'")["n"] == 0


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def _fake_github(monkeypatch, gh_id: int = 4242, email: str = "octo@example.com") -> None:
    monkeypatch.setattr(auth_service.httpx, "post", lambda *a, **k: _FakeResponse(200, {"access_token": "gho_test"}))

    def fake_get(url: str, **kwargs: Any) -> _FakeResponse:
        if url.endswith("/user"):
            return _FakeResponse(200, {"id": gh_id, "login": "octocat", "name": "Octo Cat", "avatar_url": None, "email": email})
        return _FakeResponse(200, [])

    monkeypatch.setattr(auth_service.httpx, "get", fake_get)


def test_new_github_account_gets_welcome_signup_event_and_is_new_user(client, fake_resend, inline_sends, configured,
                                                                       events, monkeypatch):
    _fake_github(monkeypatch)
    resp = client.post("/api/auth/github/callback", json={"code": "abc"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_new_user"] is True
    uid = body["user"]["id"]
    assert (uid, "signup_completed", {"method": "github", "user_type": "developer"}) in events
    assert fake_resend.to() == ["octo@example.com"]
    assert fake_resend.calls[0][1] == {"idempotency_key": f"welcome:{uid}"}

    # Logging in again is not a new account and sends nothing more.
    again = client.post("/api/auth/github/callback", json={"code": "abc"})
    assert again.json()["is_new_user"] is False
    assert len(fake_resend.calls) == 1


# ---------------------------------------------------------------------------
# /auth/me/welcome acquisition answer
# ---------------------------------------------------------------------------

def _profile(email: str) -> dict:
    return fetch_one(
        "SELECT dp.welcomed_at, dp.acquisition_source, dp.acquisition_prompt FROM developer_profiles dp "
        "JOIN users u ON u.id = dp.user_id WHERE u.email = ?", (email,),
    )


def test_welcome_patch_stores_the_acquisition_answer(client):
    _signup(client, "dev@example.com")
    headers = _login(client, "dev@example.com")

    assert client.post("/api/auth/me/welcome", json={}, headers=headers).status_code == 204
    assert _profile("dev@example.com")["welcomed_at"] is not None

    resp = client.patch("/api/auth/me/welcome", headers=headers, json={
        "acquisition_source": "ChatGPT", "acquisition_prompt": "  where can I practice coding with Claude Code  ",
    })
    assert resp.status_code == 204
    profile = _profile("dev@example.com")
    assert profile["acquisition_source"] == "chatgpt"
    assert profile["acquisition_prompt"] == "where can I practice coding with Claude Code"

    assert client.patch("/api/auth/me/welcome", headers=headers, json={"acquisition_source": "friend"}).status_code == 204
    assert _profile("dev@example.com")["acquisition_source"] == "friend"
    assert _profile("dev@example.com")["acquisition_prompt"] is None


def test_welcome_patch_validates_the_acquisition_answer(client):
    _signup(client, "dev@example.com")
    headers = _login(client, "dev@example.com")
    bad_source = client.patch("/api/auth/me/welcome", headers=headers, json={"acquisition_source": "drop table; --"})
    assert bad_source.status_code == 422
    too_long = client.patch("/api/auth/me/welcome", headers=headers,
                            json={"acquisition_source": "chatgpt", "acquisition_prompt": "x" * 501})
    assert too_long.status_code == 422
    assert client.patch("/api/auth/me/welcome", headers=headers, json={"acquisition_source": "x" * 41}).status_code == 422
    assert _profile("dev@example.com")["acquisition_source"] is None


def test_welcome_post_without_a_body_still_works(client):
    _signup(client, "dev@example.com")
    headers = _login(client, "dev@example.com")
    assert client.post("/api/auth/me/welcome", headers=headers).status_code == 204
    assert client.get("/api/auth/me", headers=headers).json()["welcomed"] is True


# ---------------------------------------------------------------------------
# first_score milestone and scoring events
# ---------------------------------------------------------------------------

def test_first_score_is_sent_once_for_the_first_eligible_score(fake_resend, configured):
    user = make_user("dev@example.com", hours_ago=48)
    make_submission(user, started_hours_ago=2, scored_hours_ago=0.01, score=81.6, share_token="tok_share")

    lifecycle.on_submission_scored(user, True)
    assert len(fake_resend.calls) == 1
    params, options = fake_resend.calls[0]
    assert options == {"idempotency_key": f"milestone:first_score:{user}"}
    assert params["subject"] == "Your kodwai score is in: 82/100"
    assert "/s/tok_share?utm_source=email" in params["text"]

    make_submission(user, slug="secrets-vault-with-envelope-encryption", started_hours_ago=1, scored_hours_ago=0.005)
    lifecycle.on_submission_scored(user, True)
    assert len(fake_resend.calls) == 1


def test_first_score_skips_ineligible_scores_and_a_disabled_flag(fake_resend, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "founder@example.com")
    user = make_user("dev@example.com", hours_ago=48)
    make_submission(user, started_hours_ago=2, scored_hours_ago=0.01)
    lifecycle.on_submission_scored(user, True)  # flag off
    execute("UPDATE feature_flags SET enabled = 1 WHERE key = 'lifecycle_emails'")
    lifecycle.on_submission_scored(user, False)  # ineligible score
    assert fake_resend.calls == []


def test_first_score_links_the_results_page_without_a_share_token(fake_resend, configured):
    user = make_user("dev@example.com", hours_ago=48)
    sid = make_submission(user, started_hours_ago=2, scored_hours_ago=0.01)
    lifecycle.on_submission_scored(user, True)
    assert f"/dev/submissions/{sid}?utm_source=email" in fake_resend.calls[0][0]["text"]


def test_scoring_hook_emits_submission_scored_and_calls_the_milestone(monkeypatch, events):
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(lifecycle, "on_submission_scored", lambda uid, eligible: calls.append((uid, eligible)))
    engine._after_scored({"id": "s1", "user_id": "u1"}, {"slug": "bookshelf-rest-api"}, 64.0, 1)
    assert ("u1", "submission_scored", {"submission_id": "s1", "challenge_slug": "bookshelf-rest-api",
                                        "score": 64.0, "leaderboard_eligible": True}) in events
    assert calls == [("u1", True)]


def test_cli_login_and_submission_started_events(client, events, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_ANTHROPIC_API_KEY", "sk-ant-test")
    _signup(client, "dev@example.com")
    headers = _login(client, "dev@example.com")
    uid = fetch_one("SELECT id FROM users WHERE email = 'dev@example.com'")["id"]

    code = client.post("/api/auth/cli/authorize", headers=headers).json()["code"]
    assert client.post("/api/auth/cli/token", json={"code": code}).status_code == 200
    assert (uid, "cli_login", {}) in events

    resp = client.post("/api/challenges/bookshelf-rest-api/start", headers=headers)
    assert resp.status_code == 201, resp.text
    started = [e for e in events if e[1] == "submission_started"]
    assert started and started[0][0] == uid
    assert started[0][2]["challenge_slug"] == "bookshelf-rest-api"


def test_acquisition_answer_never_reaches_the_public_profile(client):
    _signup(client, "dev@example.com")
    headers = _login(client, "dev@example.com")
    client.patch("/api/auth/me/welcome", headers=headers,
                 json={"acquisition_source": "chatgpt", "acquisition_prompt": "private question"})
    username = fetch_one("SELECT username FROM users WHERE email = 'dev@example.com'")["username"]

    public = client.get(f"/api/developers/{username}").json()
    for field in ("acquisition_source", "acquisition_prompt", "free_submissions_used", "welcomed_at"):
        assert field not in public
    assert public["search_indexable"] is False
    assert "private question" not in str(public)

    # The owner can opt in to search indexing; their own profile still shows their answer.
    assert client.put("/api/developers/me", headers=headers, json={"search_indexable": True}).status_code == 200
    assert client.get(f"/api/developers/{username}").json()["search_indexable"] is True
    assert client.get("/api/developers/me", headers=headers).json()["acquisition_source"] == "chatgpt"
