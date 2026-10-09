from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.errors import DownloaderError, ErrorCode
from tests.conftest import TEST_TOKEN

URL = "https://example.com/watch?v=1"


@pytest.fixture
def app(settings, service):
    return create_app(settings, service)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def events(client: TestClient, job_id: str) -> list[dict]:
    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    return [json.loads(line[len("data: "):]) for line in body.splitlines() if line.startswith("data: ")]


def download(client: TestClient, preset: str = "720p", headers: dict | None = None) -> dict:
    response = client.post("/api/downloads", json={"url": URL, "preset": preset}, headers=headers or {})
    assert response.status_code == 202
    return response.json()


def test_probe_returns_title_and_options(client):
    response = client.post("/api/probe", json={"url": URL})
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Cat video"
    assert [o["id"] for o in body["options"]][:2] == ["best", "720p"]


def test_probe_private_url_is_403_blocked_host(client):
    response = client.post("/api/probe", json={"url": "http://127.0.0.1/x"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "blocked_host"


def test_probe_extractor_error_keeps_its_code(client, fake_extractor):
    fake_extractor.probe_error = DownloaderError(ErrorCode.UNSUPPORTED_SITE, "No.")
    response = client.post("/api/probe", json={"url": URL})
    assert response.status_code == 422 and response.json()["error"]["code"] == "unsupported_site"


def test_validation_error_uses_error_body(client):
    response = client.post("/api/probe", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_download_flow_over_sse_then_download_the_file(client, fake_extractor):
    job = download(client)
    got = events(client, job["job_id"])
    assert got[0]["type"] == "queued" and got[-1]["type"] == "done"
    file = got[-1]["file"]
    assert "vd_session" in client.cookies

    assert [f["file_id"] for f in client.get("/api/files").json()] == [file["file_id"]]
    path = file["download_url"].split("/api/", 1)[1]
    response = client.get("/api/" + path)
    assert response.status_code == 200
    assert response.content == fake_extractor.content
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_job_status_endpoint(client):
    job = download(client)
    events(client, job["job_id"])
    body = client.get(f"/api/jobs/{job['job_id']}").json()
    assert body["state"] == "done" and body["file"]["name"] == "Cat video.mp4"


def test_other_browser_cannot_see_job_or_file(app, client):
    job = download(client)
    final = events(client, job["job_id"])[-1]
    stranger = TestClient(app)
    assert stranger.get("/api/files").json() == []
    assert stranger.get(f"/api/jobs/{job['job_id']}").status_code == 404
    assert stranger.delete(f"/api/files/{final['file_id']}").status_code == 404


def test_download_with_bad_signature_is_404(client):
    job = download(client)
    file = events(client, job["job_id"])[-1]["file"]
    bad = f"/api/files/{file['file_id']}/download?exp=9999999999&sig=nope"
    assert client.get(bad).status_code == 404


def test_delete_file(client):
    job = download(client)
    file_id = events(client, job["job_id"])[-1]["file_id"]
    assert client.delete(f"/api/files/{file_id}").status_code == 204
    assert client.get("/api/files").json() == []


def test_cancel_endpoint(client, fake_extractor):
    import threading

    fake_extractor.hold = threading.Event()
    job = download(client)
    assert client.post(f"/api/jobs/{job['job_id']}/cancel").status_code == 202
    assert events(client, job["job_id"])[-1]["code"] == "cancelled"


def test_shutdown_cancels_running_downloads(app, service, fake_extractor):
    import threading

    from src.service import Caller

    fake_extractor.hold = threading.Event()  # not released: only a cancel ends the download
    try:
        with TestClient(app) as client:
            job_id = download(client)["job_id"]
            job = service.get_job(Caller("admin", privileged=True), job_id)
        assert job.cancel_event.is_set()
    finally:
        fake_extractor.hold.set()  # never leave a worker thread spinning


def test_sse_sends_keepalive_comments_while_idle(settings, service, fake_extractor, monkeypatch):
    import threading

    from src.api import downloads as downloads_api

    monkeypatch.setattr(downloads_api, "KEEPALIVE_SECONDS", 0.05)
    fake_extractor.hold = threading.Event()
    app = create_app(settings, service)
    with TestClient(app) as client:
        job_id = download(client)["job_id"]
        threading.Timer(0.4, fake_extractor.hold.set).start()
        with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
            body = "".join(response.iter_text())
    assert ": ping" in body
    assert json.loads([l for l in body.splitlines() if l.startswith("data: ")][-1][6:])["type"] == "done"


def test_token_caller_acts_as_mcp_user_and_sees_any_file(client):
    job = download(client)
    file_id = events(client, job["job_id"])[-1]["file_id"]
    privileged = {"X-Internal-Token": TEST_TOKEN, "X-Requester-Username": "alice"}
    assert client.get("/api/files", headers=privileged).json() == []  # own mcp session is empty
    assert client.get(f"/api/jobs/{job['job_id']}", headers=privileged).status_code == 200  # privileged callers see any job
    assert client.delete(f"/api/files/{file_id}", headers=privileged).status_code == 404  # delete only your own


def test_mcp_endpoint_requires_internal_token(client):
    assert client.post("/mcp", json={}).status_code == 401
    assert client.post("/mcp", json={}, headers={"X-Internal-Token": "wrong"}).status_code == 401
