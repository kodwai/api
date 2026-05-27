"""Tests for the time-boxed Event system (KOD-77)."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import execute, fetch_one, fetch_all
from app.core.security import hash_password


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc(dt: datetime) -> str:
    """Format datetime as the ISO-ish string SQLite stores ('YYYY-MM-DD HH:MM:SS')."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_admin_headers(client: TestClient) -> dict[str, str]:
    """Create a superadmin user in the DB and return admin JWT headers."""
    uid = secrets.token_hex(16)
    password = "AdminPass2024!"
    org_id = secrets.token_hex(16)

    # Create a minimal org first (users.organization_id FK)
    execute(
        "INSERT INTO organizations (id, name) VALUES (?, ?)",
        (org_id, "Admin Org"),
    )
    execute(
        """INSERT INTO users (id, email, password_hash, name, role, organization_id,
                              email_verified, is_superadmin)
           VALUES (?, ?, ?, ?, 'admin', ?, 1, 1)""",
        (uid, "superadmin@test.com", hash_password(password), "Super Admin", org_id),
    )

    resp = client.post("/api/admin/login", json={
        "email": "superadmin@test.com",
        "password": password,
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_developer(email: str, name: str, username: str) -> str:
    """Insert a user + developer_profile; return user_id."""
    org_id = secrets.token_hex(16)
    uid = secrets.token_hex(16)
    execute("INSERT INTO organizations (id, name) VALUES (?, ?)", (org_id, f"Org-{username}"))
    execute(
        """INSERT INTO users (id, email, password_hash, name, username, role,
                              organization_id, email_verified)
           VALUES (?, ?, ?, ?, ?, 'admin', ?, 1)""",
        (uid, email, hash_password("pass1234"), name, username, org_id),
    )
    execute(
        "INSERT OR IGNORE INTO developer_profiles (user_id) VALUES (?)",
        (uid,),
    )
    return uid


def _add_scored_submission(
    user_id: str,
    challenge_id: str,
    score: float,
    scored_at: str,
    leaderboard_eligible: int = 1,
    agent_used: str = "claude-code",
) -> str:
    """Insert a pre-scored submission; return submission_id."""
    sub_id = secrets.token_hex(16)
    execute(
        """INSERT INTO submissions
               (id, user_id, challenge_id, status, score, leaderboard_eligible,
                scored_at, agent_used, started_at, submitted_at)
           VALUES (?, ?, ?, 'scored', ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (sub_id, user_id, challenge_id, score, leaderboard_eligible, scored_at, agent_used),
    )
    return sub_id


def _ensure_challenge(client: TestClient, admin_headers: dict) -> str:
    """Return an existing challenge id, creating one if none exist."""
    row = fetch_one("SELECT id FROM challenges LIMIT 1")
    if row:
        return row["id"]
    # Create via admin endpoint
    resp = client.post("/api/admin/challenges", headers=admin_headers, json={
        "title": "Event Test Challenge",
        "slug": "event-test-challenge",
        "description": "A challenge for event tests",
        "problem_statement_md": "# Build it",
        "difficulty": "easy",
        "category": "backend",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    return _make_admin_headers(client)


@pytest.fixture
def event_window():
    """Return (starts_at, ends_at) strings for a window of now-1h .. now+1h."""
    now = _now()
    return _utc(now - timedelta(hours=1)), _utc(now + timedelta(hours=1))


# ---------------------------------------------------------------------------
# Admin: create event
# ---------------------------------------------------------------------------

def test_admin_create_event(client: TestClient, admin_headers, event_window):
    starts_at, ends_at = event_window
    resp = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Test Event",
        "slug": "test-event",
        "description": "An event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["slug"] == "test-event"
    assert data["is_finalized"] == 0


def test_non_admin_cannot_create_event(client: TestClient, auth_headers, event_window):
    """Regular user gets 401/403 when trying to create an event."""
    starts_at, ends_at = event_window
    resp = client.post("/api/admin/events", headers=auth_headers, json={
        "title": "Sneaky Event",
        "slug": "sneaky",
        "starts_at": starts_at,
        "ends_at": ends_at,
    })
    # auth_headers carries a regular JWT — admin endpoint expects type="admin" claim
    assert resp.status_code in (401, 403)


def test_create_event_duplicate_slug(client: TestClient, admin_headers, event_window):
    starts_at, ends_at = event_window
    body = {
        "title": "Dup Event",
        "slug": "dup-slug",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    client.post("/api/admin/events", headers=admin_headers, json=body)
    resp = client.post("/api/admin/events", headers=admin_headers, json=body)
    assert resp.status_code == 409


def test_create_event_ends_before_starts(client: TestClient, admin_headers):
    now = _now()
    resp = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Bad Window",
        "slug": "bad-window",
        "starts_at": _utc(now + timedelta(hours=2)),
        "ends_at": _utc(now + timedelta(hours=1)),
    })
    assert resp.status_code == 400


def test_create_event_ends_equal_starts(client: TestClient, admin_headers):
    now = _now()
    ts = _utc(now)
    resp = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Zero Window",
        "slug": "zero-window",
        "starts_at": ts,
        "ends_at": ts,
    })
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Public: list / get
# ---------------------------------------------------------------------------

def test_list_events(client: TestClient, admin_headers, event_window):
    starts_at, ends_at = event_window
    client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Listed Event",
        "slug": "listed-event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    })
    resp = client.get("/api/events")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) >= 1
    e = next(ev for ev in events if ev["slug"] == "listed-event")
    assert e["status"] == "active"
    assert "is_finalized" in e


def test_get_event_by_id(client: TestClient, admin_headers, event_window):
    starts_at, ends_at = event_window
    created = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Get By ID",
        "slug": "get-by-id",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }).json()
    resp = client.get(f"/api/events/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "get-by-id"


def test_get_event_by_slug(client: TestClient, admin_headers, event_window):
    starts_at, ends_at = event_window
    client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Get By Slug",
        "slug": "get-by-slug",
        "starts_at": starts_at,
        "ends_at": ends_at,
    })
    resp = client.get("/api/events/get-by-slug")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Get By Slug"


def test_get_event_not_found(client: TestClient):
    resp = client.get("/api/events/does-not-exist")
    assert resp.status_code == 404


def test_event_status_upcoming(client: TestClient, admin_headers):
    now = _now()
    starts_at = _utc(now + timedelta(hours=1))
    ends_at = _utc(now + timedelta(hours=2))
    client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Future Event",
        "slug": "future-event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    })
    resp = client.get("/api/events/future-event")
    assert resp.json()["status"] == "upcoming"


def test_event_status_ended(client: TestClient, admin_headers):
    now = _now()
    starts_at = _utc(now - timedelta(hours=2))
    ends_at = _utc(now - timedelta(hours=1))
    client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Past Event",
        "slug": "past-event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    })
    resp = client.get("/api/events/past-event")
    assert resp.json()["status"] == "ended"


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def test_event_leaderboard_ranks_in_window_by_score(client: TestClient, admin_headers, event_window):
    """Two in-window submissions ranked by score desc; out-of-window excluded."""
    starts_at, ends_at = event_window
    now = _now()

    # Create event
    ev = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Leaderboard Event",
        "slug": "lb-event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }).json()

    # Fetch or create a challenge
    challenge_id = _ensure_challenge(client, admin_headers)

    # Three developers
    u1 = _create_developer("dev1@test.com", "Dev One", "dev1")
    u2 = _create_developer("dev2@test.com", "Dev Two", "dev2")
    u3 = _create_developer("dev3@test.com", "Dev Three", "dev3")

    # u1: in-window, score=90
    _add_scored_submission(u1, challenge_id, 90.0, _utc(now - timedelta(minutes=30)))
    # u2: in-window, score=75
    _add_scored_submission(u2, challenge_id, 75.0, _utc(now - timedelta(minutes=20)))
    # u3: scored AFTER ends_at — must be excluded
    _add_scored_submission(u3, challenge_id, 95.0, _utc(now + timedelta(hours=2)))

    resp = client.get(f"/api/events/{ev['id']}/leaderboard")
    assert resp.status_code == 200
    lb = resp.json()

    # Only u1 and u2 appear
    user_ids = [e["user_id"] for e in lb]
    assert u1 in user_ids
    assert u2 in user_ids
    assert u3 not in user_ids

    # Ranked by score desc: u1 first
    assert lb[0]["user_id"] == u1
    assert lb[0]["rank"] == 1
    assert lb[1]["user_id"] == u2
    assert lb[1]["rank"] == 2


def test_event_leaderboard_excludes_ineligible(client: TestClient, admin_headers, event_window):
    """Submissions with leaderboard_eligible=0 must not appear."""
    starts_at, ends_at = event_window
    now = _now()

    ev = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Eligibility Event",
        "slug": "elig-event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }).json()

    challenge_id = _ensure_challenge(client, admin_headers)

    u_eligible = _create_developer("elig1@test.com", "Eligible One", "elig1")
    u_ineligible = _create_developer("inelig1@test.com", "Ineligible One", "inelig1")

    _add_scored_submission(u_eligible, challenge_id, 80.0, _utc(now - timedelta(minutes=10)), leaderboard_eligible=1)
    _add_scored_submission(u_ineligible, challenge_id, 99.0, _utc(now - timedelta(minutes=10)), leaderboard_eligible=0)

    resp = client.get(f"/api/events/{ev['id']}/leaderboard")
    assert resp.status_code == 200
    lb = resp.json()
    user_ids = [e["user_id"] for e in lb]
    assert u_eligible in user_ids
    assert u_ineligible not in user_ids


def test_event_leaderboard_tiebreak_by_earliest(client: TestClient, admin_headers, event_window):
    """When two users have the same score, earliest scored_at wins."""
    starts_at, ends_at = event_window
    now = _now()

    ev = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Tiebreak Event",
        "slug": "tie-event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }).json()

    challenge_id = _ensure_challenge(client, admin_headers)

    u_early = _create_developer("early@test.com", "Early User", "earlyuser")
    u_late = _create_developer("late@test.com", "Late User", "lateuser")

    # Same score, u_early scored first
    _add_scored_submission(u_early, challenge_id, 85.0, _utc(now - timedelta(minutes=50)))
    _add_scored_submission(u_late, challenge_id, 85.0, _utc(now - timedelta(minutes=10)))

    resp = client.get(f"/api/events/{ev['id']}/leaderboard")
    lb = resp.json()
    assert lb[0]["user_id"] == u_early
    assert lb[1]["user_id"] == u_late


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------

def test_finalize_event(client: TestClient, admin_headers, event_window):
    """Finalize records top-3 winners, sets is_finalized=1, awards badge."""
    starts_at, ends_at = event_window
    now = _now()

    ev = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Final Event",
        "slug": "final-event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }).json()

    challenge_id = _ensure_challenge(client, admin_headers)

    u1 = _create_developer("fin1@test.com", "Finalist One", "fin1")
    u2 = _create_developer("fin2@test.com", "Finalist Two", "fin2")
    u3 = _create_developer("fin3@test.com", "Finalist Three", "fin3")
    u4 = _create_developer("fin4@test.com", "Finalist Four", "fin4")  # 4th — should not get badge

    _add_scored_submission(u1, challenge_id, 95.0, _utc(now - timedelta(minutes=50)))
    _add_scored_submission(u2, challenge_id, 80.0, _utc(now - timedelta(minutes=40)))
    _add_scored_submission(u3, challenge_id, 70.0, _utc(now - timedelta(minutes=30)))
    _add_scored_submission(u4, challenge_id, 60.0, _utc(now - timedelta(minutes=20)))

    resp = client.post(f"/api/admin/events/{ev['id']}/finalize", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_finalized"] is True
    assert len(data["winners"]) == 3

    # Verify ranks
    winners_by_rank = {w["rank"]: w for w in data["winners"]}
    assert winners_by_rank[1]["user_id"] == u1
    assert winners_by_rank[2]["user_id"] == u2
    assert winners_by_rank[3]["user_id"] == u3

    # Event flag flipped
    ev_row = fetch_one("SELECT is_finalized FROM events WHERE id = ?", (ev["id"],))
    assert ev_row["is_finalized"] == 1

    # event_winners rows in DB
    db_winners = fetch_all(
        "SELECT user_id, rank FROM event_winners WHERE event_id = ? ORDER BY rank",
        (ev["id"],),
    )
    assert len(db_winners) == 3

    # Badges awarded to top-3
    badge = fetch_one("SELECT id FROM badges WHERE slug = 'event-top-3'")
    assert badge is not None

    for uid in (u1, u2, u3):
        row = fetch_one(
            "SELECT id FROM developer_badges WHERE user_id = ? AND badge_id = ?",
            (uid, badge["id"]),
        )
        assert row is not None, f"Badge not awarded to {uid}"

    # u4 should NOT have the badge
    no_badge = fetch_one(
        "SELECT id FROM developer_badges WHERE user_id = ? AND badge_id = ?",
        (u4, badge["id"]),
    )
    assert no_badge is None


def test_finalize_event_not_found(client: TestClient, admin_headers):
    resp = client.post("/api/admin/events/nonexistent-id/finalize", headers=admin_headers)
    assert resp.status_code == 404


def test_finalize_event_idempotent(client: TestClient, admin_headers, event_window):
    """Calling finalize twice on an already-finalized event is a no-op."""
    starts_at, ends_at = event_window
    now = _now()

    ev = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Idempotent Event",
        "slug": "idem-event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }).json()

    challenge_id = _ensure_challenge(client, admin_headers)
    u1 = _create_developer("idem1@test.com", "Idem One", "idem1")
    _add_scored_submission(u1, challenge_id, 90.0, _utc(now - timedelta(minutes=10)))

    # First finalize
    resp1 = client.post(f"/api/admin/events/{ev['id']}/finalize", headers=admin_headers)
    assert resp1.status_code == 200

    # Second finalize — should return 200 with same data, no duplicate rows
    resp2 = client.post(f"/api/admin/events/{ev['id']}/finalize", headers=admin_headers)
    assert resp2.status_code == 200

    db_winners = fetch_all(
        "SELECT id FROM event_winners WHERE event_id = ?", (ev["id"],)
    )
    assert len(db_winners) == 1  # no duplicates


def test_finalize_fewer_than_3_winners(client: TestClient, admin_headers, event_window):
    """If fewer than 3 developers competed, only those are recorded."""
    starts_at, ends_at = event_window
    now = _now()

    ev = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "Small Event",
        "slug": "small-event",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }).json()

    challenge_id = _ensure_challenge(client, admin_headers)
    u1 = _create_developer("small1@test.com", "Small One", "small1")
    _add_scored_submission(u1, challenge_id, 70.0, _utc(now - timedelta(minutes=10)))

    resp = client.post(f"/api/admin/events/{ev['id']}/finalize", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["winners"]) == 1
    assert data["winners"][0]["rank"] == 1


# ---------------------------------------------------------------------------
# Regression: KOD-77 — datetime format mismatch (T vs space, offset vs no-tz)
# ---------------------------------------------------------------------------

def test_leaderboard_includes_submission_when_event_created_with_iso8601_offset(
    client: TestClient, admin_headers
):
    """Regression test for KOD-77.

    The bug: admin create endpoint accepted ISO-8601 strings like
    "2026-05-27T17:00:00+00:00" (T-separator, UTC offset) and stored them
    verbatim.  SQLite's datetime('now') produces "YYYY-MM-DD HH:MM:SS"
    (space-separator, no offset).  String comparison of
    "2026-05-27 18:30:00" >= "2026-05-27T17:00:00+00:00" evaluates False
    because 0x20 (space) < 0x54 ('T'), so ALL in-window submissions were
    excluded → leaderboard always empty.

    Fix: normalize starts_at/ends_at to SQLite canonical format on write, and
    wrap both sides of every scored_at comparison in datetime() in SQL.
    """
    now = _now()
    # Pass ISO-8601 strings WITH T-separator and explicit UTC offset — this is
    # the real-world format the client sends and the exact format that triggers
    # the bug.
    starts_at_iso = (now - timedelta(hours=1)).isoformat()   # e.g. "2026-05-27T17:00:00+00:00"
    ends_at_iso   = (now + timedelta(hours=2)).isoformat()   # e.g. "2026-05-27T20:00:00+00:00"

    ev = client.post("/api/admin/events", headers=admin_headers, json={
        "title": "ISO Offset Event",
        "slug": "iso-offset-event",
        "starts_at": starts_at_iso,
        "ends_at": ends_at_iso,
    }).json()
    assert ev.get("id"), f"Event creation failed: {ev}"

    challenge_id = _ensure_challenge(client, admin_headers)
    u1 = _create_developer("iso1@test.com", "ISO Dev", "isodev")

    # scored_at written via datetime('now') — SQLite canonical space-format,
    # 30 minutes ago, clearly inside the event window.
    scored_at_sqlite = _utc(now - timedelta(minutes=30))  # "YYYY-MM-DD HH:MM:SS"
    _add_scored_submission(u1, challenge_id, 88.0, scored_at_sqlite)

    resp = client.get(f"/api/events/{ev['id']}/leaderboard")
    assert resp.status_code == 200
    lb = resp.json()

    # Before the fix this list was empty; after the fix u1 must appear.
    user_ids = [e["user_id"] for e in lb]
    assert u1 in user_ids, (
        f"In-window submission excluded from leaderboard — datetime format bug not fixed. "
        f"event starts_at stored={ev.get('starts_at')!r}, "
        f"submission scored_at={scored_at_sqlite!r}, "
        f"leaderboard={lb}"
    )
