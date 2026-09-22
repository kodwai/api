"""Row factories for lifecycle email tests: users at a given signup age, CLI logins, submissions,
ledger rows, a Resend stand-in and a fully configured sender. Not collected as tests; test modules
wrap install_fake_resend and configure_lifecycle in their own fixtures."""
from __future__ import annotations

import json
import secrets
from typing import Any

import pytest

from app.core.database import execute, fetch_one
from app.services import email_service


def ago(hours: float) -> str:
    """SQLite datetime modifier for 'hours ago', e.g. '-108000 seconds'."""
    return f"-{int(hours * 3600)} seconds"


def make_user(
    email: str,
    *,
    hours_ago: float = 30,
    verified: bool = True,
    user_type: str = "developer",
    name: str = "Ada Lovelace",
    token: str | None = None,
    is_demo: int = 0,
    banned: int = 0,
    unsubscribed: bool = False,
    suppressed: bool = False,
    password_hash: str = "x",
    superadmin: int = 0,
) -> str:
    uid = secrets.token_hex(16)
    org_id = None
    if user_type == "company":
        org_id = secrets.token_hex(16)
        execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, "Org"))
    execute(
        """INSERT INTO users (id, email, password_hash, name, role, organization_id, user_type, email_verified,
                              email_verification_token, is_demo, is_banned, is_superadmin, email_unsubscribed_at,
                              email_suppressed_at, created_at)
           VALUES (?, ?, ?, ?, 'admin', ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', ?))""",
        (
            uid, email, password_hash, name, org_id, user_type, int(verified), token, is_demo, banned, superadmin,
            "2026-01-01 00:00:00" if unsubscribed else None,
            "2026-01-01 00:00:00" if suppressed else None,
            ago(hours_ago),
        ),
    )
    if user_type == "developer":
        execute("INSERT INTO developer_profiles (id, user_id) VALUES (?, ?)", (secrets.token_hex(16), uid))
    return uid


def cli_login(user_id: str, hours_ago: float = 2) -> None:
    """A finished CLI browser login (cli_auth_codes row with used_at set)."""
    execute(
        "INSERT INTO cli_auth_codes (id, user_id, code, expires_at, used_at) "
        "VALUES (?, ?, ?, datetime('now', '+10 minutes'), datetime('now', ?))",
        (secrets.token_hex(16), user_id, secrets.token_urlsafe(16), ago(hours_ago)),
    )


def challenge_id(slug: str = "bookshelf-rest-api") -> str:
    row = fetch_one("SELECT id FROM challenges WHERE slug = ?", (slug,))
    assert row, f"missing seeded challenge {slug}"
    return row["id"]


def breakdown(direction: float, outcome: float, lift: float) -> str:
    """A v2 score_breakdown with the default 50/35/15 axes."""
    return json.dumps({"axes": [
        {"name": "direction", "points": 50, "score": direction, "signals": []},
        {"name": "outcome", "points": 35, "score": outcome, "signals": []},
        {"name": "lift", "points": 15, "score": lift, "signals": []},
    ]})


def make_submission(
    user_id: str,
    *,
    status: str = "scored",
    started_hours_ago: float = 100,
    scored_hours_ago: float | None = 99,
    score: float = 72.4,
    eligible: int = 1,
    slug: str = "bookshelf-rest-api",
    score_breakdown: str | None = None,
    share_token: str | None = None,
) -> str:
    sid = secrets.token_hex(16)
    scored_at = ago(scored_hours_ago) if (status == "scored" and scored_hours_ago is not None) else None
    execute(
        """INSERT INTO submissions (id, challenge_id, user_id, status, mode, score, score_breakdown,
                                    leaderboard_eligible, share_token, started_at, scored_at)
           VALUES (?, ?, ?, ?, 'local', ?, ?, ?, ?, datetime('now', ?),
                   CASE WHEN ? IS NULL THEN NULL ELSE datetime('now', ?) END)""",
        (
            sid, challenge_id(slug), user_id, status, score if status == "scored" else None,
            score_breakdown, eligible, share_token, ago(started_hours_ago), scored_at, scored_at,
        ),
    )
    return sid


def ledger_row(
    user_id: str,
    template: str,
    *,
    hours_ago: float = 1,
    status: str = "sent",
    stream: str = "lifecycle",
    dedupe_key: str | None = None,
    to_email: str = "someone@example.com",
    provider_id: str | None = None,
    attempts: int = 1,
) -> str:
    rid = secrets.token_hex(16)
    execute(
        """INSERT INTO email_sends (id, user_id, to_email, template, stream, dedupe_key, status, attempts,
                                    provider_id, created_at, sent_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', ?), datetime('now', ?))""",
        (rid, user_id, to_email, template, stream, dedupe_key or f"{template}:{user_id}:{rid[:6]}", status,
         attempts, provider_id, ago(hours_ago), ago(hours_ago)),
    )
    return rid


def welcomed(user_id: str, hours_ago: float) -> None:
    """The welcome already went out (keeps the welcome backstop out of drip tests)."""
    ledger_row(user_id, "welcome", hours_ago=hours_ago, dedupe_key=f"welcome:{user_id}")


class FakeResend:
    """Stands in for resend.Emails.send and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    def send(self, params: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append((params, options))
        return {"id": f"re_{len(self.calls)}"}

    def to(self) -> list[str]:
        return [params["to"][0] for params, _ in self.calls]


def install_fake_resend(monkeypatch: pytest.MonkeyPatch) -> FakeResend:
    """Replace resend.Emails.send with a recorder (test modules wrap this in a fixture)."""
    fake = FakeResend()
    monkeypatch.setattr(email_service.resend.Emails, "send", fake.send)
    return fake


def configure_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything a real lifecycle send needs, with the lifecycle_emails flag on."""
    monkeypatch.setattr("app.core.config.settings.RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr("app.core.config.settings.EMAIL_REPLY_TO", "founder@example.com")
    execute("UPDATE feature_flags SET enabled = 1 WHERE key = 'lifecycle_emails'")
