from __future__ import annotations

from fastapi.testclient import TestClient

from src.app import create_app


def test_health(settings):
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
