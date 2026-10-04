from __future__ import annotations

from starlette.testclient import TestClient

from src.run import build_app


def test_build_app_wires_up_health_route():
    with TestClient(build_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
