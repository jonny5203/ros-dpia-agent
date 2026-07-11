"""Health endpoint tests. Reachability is mocked so they don't hit the network."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.ai.providers.openrouter import OpenRouterClient
from app.main import create_app


def test_health_ok_when_openrouter_reachable(monkeypatch):
    async def fake_reachability(self, cache_ttl: float = 30.0):
        return {
            "base_url": "https://openrouter.ai/api/v1",
            "key_configured": True,
            "reachable": True,
            "key_valid": True,
        }

    monkeypatch.setattr(OpenRouterClient, "reachability", fake_reachability)

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "dpia-ros-backend"
    assert body["openrouter"]["reachable"] is True
    assert body["openrouter"]["key_valid"] is True


def test_health_degraded_when_openrouter_unreachable(monkeypatch):
    async def fake_reachability(self, cache_ttl: float = 30.0):
        return {
            "base_url": "https://openrouter.ai/api/v1",
            "key_configured": False,
            "reachable": False,
            "key_valid": None,
            "error": "ConnectError",
        }

    monkeypatch.setattr(OpenRouterClient, "reachability", fake_reachability)

    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/health")

    assert resp.status_code == 200  # still 200 — container stays healthy
    assert resp.json()["status"] == "degraded"


def test_error_is_problem_json():
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/api/does-not-exist")

    assert resp.status_code == 404
    assert resp.headers["content-type"] == "application/problem+json"
    body = resp.json()
    assert body["title"] == "Not Found"
    assert body["status"] == 404
