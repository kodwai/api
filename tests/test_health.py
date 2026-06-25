"""Health check tests."""
from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
