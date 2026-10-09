from fastapi.testclient import TestClient

from src.app import create_app


def test_health_reports_versions(settings, service):
    with TestClient(create_app(settings, service)) as client:
        body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["yt_dlp"]
    assert isinstance(body["ffmpeg"], bool)
