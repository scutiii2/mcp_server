from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import Limits
from tests.conftest import TEST_TOKEN, make_image, make_pdf, page_widths


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def upload(client: TestClient, path: Path, headers: dict | None = None):
    return client.post(
        "/api/files", content=path.read_bytes(), headers={"X-Filename": quote(path.name), **(headers or {})}
    )


def events(client: TestClient, job_id: str) -> list[dict]:
    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    return [json.loads(line[len("data: ") :]) for line in body.splitlines() if line.startswith("data: ")]


def test_upload_sets_cookie_and_lists_file(client, tmp_path: Path):
    response = upload(client, make_pdf(tmp_path / "résumé.pdf", [100, 101]))

    assert response.status_code == 201
    info = response.json()
    assert (info["name"], info["kind"], info["pages"]) == ("résumé.pdf", "pdf", 2)
    assert "pm_session" in client.cookies
    assert [f["file_id"] for f in client.get("/api/files").json()] == [info["file_id"]]


def test_other_browser_cannot_see_the_file(app, client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    stranger = TestClient(app)  # no "with": the app's lifespan may run only once
    assert stranger.get("/api/files").json() == []
    response = stranger.get(f"/api/files/{file_id}/content")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "file_not_found"


def test_content_is_served_inline(client, tmp_path: Path):
    path = make_pdf(tmp_path / "a.pdf", [100])
    file_id = upload(client, path).json()["file_id"]

    response = client.get(f"/api/files/{file_id}/content")

    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_unsupported_type_body(client, tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text("hello")

    response = upload(client, text)

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_type"


def test_declared_size_over_limit_is_refused_early(settings):
    small = dataclasses.replace(settings, limits=Limits(max_file_bytes=10))

    with TestClient(create_app(small)) as client:
        response = client.post("/api/files", content=b"x" * 11, headers={"X-Filename": "a.pdf"})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"


def test_merge_streams_events_and_download_works(client, tmp_path: Path):
    pdf = upload(client, make_pdf(tmp_path / "a.pdf", [100, 101])).json()
    img = upload(client, make_image(tmp_path / "b.jpg")).json()
    plan = {
        "segments": [{"file_id": pdf["file_id"], "pages": "2"}, {"file_id": img["file_id"]}],
        "output": {"filename": "out.pdf"},
    }

    started = client.post("/api/merge", json=plan)
    assert started.status_code == 202
    stream = events(client, started.json()["job_id"])

    assert stream[0]["type"] == "queued"
    done = stream[-1]
    assert done["type"] == "done" and done["pages"] == 2
    link = urlsplit(done["download_url"])
    download = client.get(f"{link.path}?{link.query}")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith("attachment;")
    assert download.headers["x-content-type-options"] == "nosniff"
    out = tmp_path / "downloaded.pdf"
    out.write_bytes(download.content)
    assert page_widths(out)[0] == 101


def test_tampered_download_link_is_not_found(client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    response = client.get(f"/api/files/{file_id}/download?exp=99999999999&sig={'0' * 64}")

    assert response.status_code == 404


def test_bad_plan_fails_immediately(client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    response = client.post("/api/merge", json={"segments": [{"file_id": file_id, "pages": "5"}]})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_range"


def test_malformed_body_is_invalid_request(client):
    response = client.post("/api/merge", json={"segments": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_delete(client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    assert client.delete(f"/api/files/{file_id}").status_code == 204
    assert client.get("/api/files").json() == []


def test_token_caller_can_use_a_web_file_by_id(app, client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    bot = TestClient(app)
    headers = {"X-Internal-Token": TEST_TOKEN, "X-Requester-Username": "alice"}
    assert bot.get(f"/api/files/{file_id}/content", headers=headers).status_code == 200
    assert bot.get("/api/files", headers=headers).json() == []


def test_wrong_token_is_treated_as_a_browser(app, client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]

    response = TestClient(app).get(f"/api/files/{file_id}/content", headers={"X-Internal-Token": "wrong"})
    assert response.status_code == 404


def test_non_ascii_token_header_is_treated_as_a_browser(app):
    bot = TestClient(app)

    response = bot.get("/api/files", headers=[(b"x-internal-token", "é".encode("latin-1"))])

    assert response.status_code == 200
    assert response.json() == []


def test_unexpected_error_is_a_json_500_without_details(app, service, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret")

    monkeypatch.setattr(app.state.service, "list_files", boom)

    response = TestClient(app, raise_server_exceptions=False).get("/api/files")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text


def test_content_length_guard_ignores_non_ascii_digits():
    from src.api.files import declared_size

    assert declared_size("²") is None
    assert declared_size("12") == 12
    assert declared_size("") is None


def test_other_browser_cannot_follow_the_job(app, client, tmp_path: Path):
    file_id = upload(client, make_pdf(tmp_path / "a.pdf", [100])).json()["file_id"]
    job_id = client.post("/api/merge", json={"segments": [{"file_id": file_id}]}).json()["job_id"]

    response = TestClient(app).get(f"/api/jobs/{job_id}/events")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "job_not_found"


def test_session_cookie_is_renewed_on_every_request(client, tmp_path: Path):
    first = upload(client, make_pdf(tmp_path / "a.pdf", [100]))
    value = client.cookies["pm_session"]
    assert "pm_session=" in first.headers["set-cookie"]

    second = client.get("/api/files")

    assert f"pm_session={value}" in second.headers["set-cookie"]
    assert "HttpOnly" in second.headers["set-cookie"]
