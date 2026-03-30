"""Project endpoint tests."""
from __future__ import annotations

from fastapi.testclient import TestClient


SAMPLE_PROJECT = {
    "title": "Rate Limiter Challenge",
    "description": "Build a distributed rate limiter",
    "problem_statement_md": "# Rate Limiter\n\nBuild a rate limiter that handles 10M req/s.",
    "time_limit_minutes": 60,
    "difficulty": "medium",
    "rubric": [
        {"name": "Code Quality", "weight": 8, "description": "Clean, readable code"},
        {"name": "Problem Solving", "weight": 7, "description": "Effective approach"},
    ],
    "max_budget_usd": 5.0,
}


def _create_project(client: TestClient, headers: dict, **overrides) -> dict:
    data = {**SAMPLE_PROJECT, **overrides}
    resp = client.post("/api/projects", headers=headers, json=data)
    assert resp.status_code == 201
    return resp.json()


# ── Create ──────────────────────────────────────────────────


def test_create_project(client: TestClient, auth_headers):
    data = _create_project(client, auth_headers)
    assert data["title"] == "Rate Limiter Challenge"
    assert data["difficulty"] == "medium"
    assert data["time_limit_minutes"] == 60
    assert len(data["rubric"]) == 2
    assert data["is_archived"] is False
    assert "id" in data


def test_create_project_minimal(client: TestClient, auth_headers):
    resp = client.post("/api/projects", headers=auth_headers, json={
        "title": "Minimal",
        "problem_statement_md": "Do something",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Minimal"
    assert data["time_limit_minutes"] == 60  # default


def test_create_project_missing_title(client: TestClient, auth_headers):
    resp = client.post("/api/projects", headers=auth_headers, json={
        "problem_statement_md": "Do something",
    })
    assert resp.status_code == 422


def test_create_project_unauthenticated(client: TestClient):
    resp = client.post("/api/projects", json=SAMPLE_PROJECT)
    assert resp.status_code == 401


# ── List ────────────────────────────────────────────────────


def test_list_projects(client: TestClient, auth_headers):
    _create_project(client, auth_headers, title="Project 1")
    _create_project(client, auth_headers, title="Project 2")

    resp = client.get("/api/projects", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_projects_excludes_archived(client: TestClient, auth_headers):
    p = _create_project(client, auth_headers, title="Active")
    _create_project(client, auth_headers, title="To Archive")

    projects = client.get("/api/projects", headers=auth_headers).json()
    archive_id = [p for p in projects if p["title"] == "To Archive"][0]["id"]
    client.delete(f"/api/projects/{archive_id}", headers=auth_headers)

    resp = client.get("/api/projects", headers=auth_headers)
    assert len(resp.json()) == 1
    assert resp.json()[0]["title"] == "Active"


def test_list_projects_cross_org_isolation(client: TestClient, auth_headers, second_user_headers):
    _create_project(client, auth_headers, title="Org1 Project")
    _create_project(client, second_user_headers, title="Org2 Project")

    resp1 = client.get("/api/projects", headers=auth_headers)
    resp2 = client.get("/api/projects", headers=second_user_headers)

    assert len(resp1.json()) == 1
    assert resp1.json()[0]["title"] == "Org1 Project"
    assert len(resp2.json()) == 1
    assert resp2.json()[0]["title"] == "Org2 Project"


# ── Get ─────────────────────────────────────────────────────


def test_get_project(client: TestClient, auth_headers):
    p = _create_project(client, auth_headers)
    resp = client.get(f"/api/projects/{p['id']}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Rate Limiter Challenge"


def test_get_project_not_found(client: TestClient, auth_headers):
    resp = client.get("/api/projects/nonexistent", headers=auth_headers)
    assert resp.status_code == 404


def test_get_project_other_org(client: TestClient, auth_headers, second_user_headers):
    p = _create_project(client, auth_headers)
    resp = client.get(f"/api/projects/{p['id']}", headers=second_user_headers)
    assert resp.status_code == 404


# ── Update ──────────────────────────────────────────────────


def test_update_project(client: TestClient, auth_headers):
    p = _create_project(client, auth_headers)
    resp = client.put(f"/api/projects/{p['id']}", headers=auth_headers, json={
        "title": "Updated Title",
        "time_limit_minutes": 90,
    })
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Title"
    assert resp.json()["time_limit_minutes"] == 90


def test_update_project_no_fields(client: TestClient, auth_headers):
    p = _create_project(client, auth_headers)
    resp = client.put(f"/api/projects/{p['id']}", headers=auth_headers, json={})
    assert resp.status_code == 400


# ── Delete (Archive) ────────────────────────────────────────


def test_archive_project(client: TestClient, auth_headers):
    p = _create_project(client, auth_headers)
    resp = client.delete(f"/api/projects/{p['id']}", headers=auth_headers)
    assert resp.status_code == 204

    # Should not appear in active list
    resp = client.get("/api/projects", headers=auth_headers)
    assert len(resp.json()) == 0

    # Should appear in archived list
    resp = client.get("/api/projects?is_archived=true", headers=auth_headers)
    assert len(resp.json()) == 1


# ── Duplicate ───────────────────────────────────────────────


def test_duplicate_project(client: TestClient, auth_headers):
    p = _create_project(client, auth_headers)
    resp = client.post(f"/api/projects/{p['id']}/duplicate", headers=auth_headers)
    assert resp.status_code == 201
    dup = resp.json()
    assert dup["title"] == "Rate Limiter Challenge (Copy)"
    assert dup["id"] != p["id"]
    assert dup["difficulty"] == p["difficulty"]
    assert len(dup["rubric"]) == len(p["rubric"])

    # Should now have 2 projects
    resp = client.get("/api/projects", headers=auth_headers)
    assert len(resp.json()) == 2
