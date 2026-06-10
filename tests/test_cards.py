"""Tests for the embeddable developer rank card (SVG)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.database import execute, fetch_one


def _create_developer(client: TestClient, email: str, name: str, rating: int) -> str:
    """Sign up a developer, set their direction_rating, return their username."""
    resp = client.post("/api/auth/signup", json={
        "email": email,
        "password": "testpass123",
        "name": name,
        "user_type": "developer",
    })
    assert resp.status_code == 201

    user = fetch_one("SELECT id, username FROM users WHERE email = ?", (email,))
    assert user is not None
    # A developer_profiles row should have been created on signup.
    profile = fetch_one("SELECT id FROM developer_profiles WHERE user_id = ?", (user["id"],))
    assert profile is not None

    execute(
        "UPDATE developer_profiles SET direction_rating = ?, rank = ?, "
        "challenges_completed = ?, streak_days = ? WHERE user_id = ?",
        (rating, 3, 12, 5, user["id"]),
    )
    return user["username"]


def test_developer_card_returns_svg(client: TestClient) -> None:
    username = _create_developer(client, "carddev@test.com", "Card Dev", 1200)

    resp = client.get(f"/api/developers/{username}/card.svg")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    body = resp.text
    assert "<svg" in body
    assert f"@{username}" in body
    assert "DIRECTION RATING" in body
    # rating 1200 -> Gold tier
    assert "GOLD" in body
    assert "1200" in body


def test_developer_card_cache_header(client: TestClient) -> None:
    username = _create_developer(client, "cachedev@test.com", "Cache Dev", 1000)
    resp = client.get(f"/api/developers/{username}/card.svg")
    assert resp.status_code == 200
    assert "max-age" in resp.headers.get("cache-control", "")


def test_developer_card_unknown_username_404(client: TestClient) -> None:
    resp = client.get("/api/developers/nope-does-not-exist/card.svg")
    assert resp.status_code == 404
