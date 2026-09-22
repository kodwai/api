"""Migrations 038-041 (email lifecycle, feedback replies, automation tokens, attribution) and
the execute_returning helper that powers claim-then-send."""
from __future__ import annotations

import secrets

from app.core.database import (
    execute,
    execute_returning,
    fetch_all,
    fetch_one,
    get_connection,
    run_migrations,
)


def _columns(table: str) -> set[str]:
    return {r[1] for r in get_connection().execute(f"PRAGMA table_info({table})").fetchall()}


def _insert_user(email: str) -> str:
    org_id, uid = secrets.token_hex(16), secrets.token_hex(16)
    execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, "Org"))
    execute(
        "INSERT INTO users (id, email, password_hash, name, organization_id) VALUES (?, ?, 'x', 'U', ?)",
        (uid, email, org_id),
    )
    return uid


def test_growth_migrations_recorded():
    names = {r["name"] for r in fetch_all("SELECT name FROM _migrations")}
    for name in ("038_email_lifecycle.sql", "039_feedback_replies.sql", "040_automation_tokens.sql", "041_growth_attribution.sql"):
        assert name in names


def test_email_lifecycle_schema():
    assert {"id", "user_id", "to_email", "template", "stream", "dedupe_key", "status", "attempts",
            "provider_id", "error", "run_id", "meta", "created_at", "sent_at"} <= _columns("email_sends")
    assert {"email_unsubscribed_at", "email_suppressed_at", "email_suppressed_reason",
            "marketing_consent_at", "is_demo"} <= _columns("users")


def test_feedback_reply_columns():
    assert {"reply_emailed_at", "reply_email_send_id"} <= _columns("platform_feedback")
    assert {"admin_response", "admin_responded_by", "admin_responded_at",
            "reply_emailed_at", "reply_email_send_id"} <= _columns("challenge_feedback")


def test_automation_tokens_and_attribution_schema():
    assert {"id", "name", "token_hash", "token_prefix", "scopes", "owner_user_id",
            "expires_at", "revoked_at", "last_used_at", "created_at"} <= _columns("automation_tokens")
    assert {"acquisition_source", "acquisition_prompt", "search_indexable"} <= _columns("developer_profiles")


def test_email_flags_default_off():
    rows = {r["key"]: r["enabled"] for r in fetch_all(
        "SELECT key, enabled FROM feature_flags WHERE key IN ('lifecycle_emails', 'feedback_ack_emails')"
    )}
    assert rows == {"lifecycle_emails": 0, "feedback_ack_emails": 0}


def test_email_sends_dedupe_key_unique():
    execute("INSERT INTO email_sends (to_email, template, dedupe_key) VALUES ('a@x.com', 'welcome', 'k1')")
    try:
        execute("INSERT INTO email_sends (to_email, template, dedupe_key) VALUES ('a@x.com', 'welcome', 'k1')")
        raised = False
    except Exception:
        raised = True
    assert raised


def test_email_sends_stream_check():
    try:
        execute("INSERT INTO email_sends (to_email, template, stream, dedupe_key) VALUES ('a@x.com', 't', 'marketing', 'k2')")
        raised = False
    except Exception:
        raised = True
    assert raised


def test_is_demo_backfill_applies_to_existing_demo_users():
    demo = _insert_user("seed@DEMO.kodwai.dev")
    real = _insert_user("real@example.com")
    # Simulate production: rows exist before 041 runs. Roll 041 back and re-apply it; its
    # developer_profiles columns already exist, so this also covers the duplicate-column skip.
    conn = get_connection()
    conn.execute("ALTER TABLE users DROP COLUMN is_demo")
    conn.execute("DELETE FROM _migrations WHERE name = '041_growth_attribution.sql'")
    conn.commit()
    run_migrations()
    assert fetch_one("SELECT is_demo FROM users WHERE id = ?", (demo,))["is_demo"] == 1
    assert fetch_one("SELECT is_demo FROM users WHERE id = ?", (real,))["is_demo"] == 0


def test_new_columns_default_values():
    uid = _insert_user("dev@example.com")
    row = fetch_one("SELECT is_demo, email_unsubscribed_at, marketing_consent_at FROM users WHERE id = ?", (uid,))
    assert row == {"is_demo": 0, "email_unsubscribed_at": None, "marketing_consent_at": None}
    execute("INSERT INTO developer_profiles (user_id) VALUES (?)", (uid,))
    profile = fetch_one("SELECT search_indexable, acquisition_source FROM developer_profiles WHERE user_id = ?", (uid,))
    assert profile == {"search_indexable": 0, "acquisition_source": None}


def test_run_migrations_is_idempotent():
    run_migrations()
    run_migrations()
    assert fetch_one("SELECT COUNT(*) AS n FROM feature_flags WHERE key = 'lifecycle_emails'")["n"] == 1


# ---------------------------------------------------------------------------
# execute_returning
# ---------------------------------------------------------------------------

def test_execute_returning_insert_returns_row():
    rows = execute_returning(
        "INSERT INTO email_sends (to_email, template, dedupe_key) VALUES (?, ?, ?) RETURNING id, status",
        ("a@x.com", "welcome", "ret-1"),
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "claimed"
    # Committed: visible to a separate read.
    assert fetch_one("SELECT id FROM email_sends WHERE dedupe_key = 'ret-1'")["id"] == rows[0]["id"]


def test_execute_returning_conflict_returns_empty():
    sql = ("INSERT INTO email_sends (to_email, template, dedupe_key) VALUES (?, ?, ?) "
           "ON CONFLICT(dedupe_key) DO NOTHING RETURNING id")
    first = execute_returning(sql, ("a@x.com", "welcome", "ret-2"))
    second = execute_returning(sql, ("a@x.com", "welcome", "ret-2"))
    assert len(first) == 1
    assert second == []
    assert fetch_one("SELECT COUNT(*) AS n FROM email_sends WHERE dedupe_key = 'ret-2'")["n"] == 1


def test_execute_returning_update_returns_changed_rows():
    execute("INSERT INTO email_sends (to_email, template, dedupe_key) VALUES ('a@x.com', 't', 'ret-3')")
    rows = execute_returning("UPDATE email_sends SET status = 'sent' WHERE dedupe_key = ? RETURNING status", ("ret-3",))
    assert rows == [{"status": "sent"}]
    assert execute_returning("UPDATE email_sends SET status = 'sent' WHERE dedupe_key = ? RETURNING id", ("nope",)) == []
