from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import FakeEmailSender
from tests.test_admin import login, make_member
from tests.test_registration import as_admin

GOOD_CONFIG = {"host": "127.0.0.1", "port": 8030, "session_hours": 12, "cookie_secure": False}


def issues(client: TestClient) -> set[tuple[str, str, str]]:
    response = client.get("/api/config-issues")
    assert response.status_code == 200, response.text
    return {(i["file"], i["key"], i["message"]) for i in response.json()}


def test_reports_config_and_secret_problems(client: TestClient, tmp_path: Path) -> None:
    as_admin(client)
    found = issues(client)
    # Local SMTP is no longer required; delivery is owned by MCP.
    assert ("config_app.json", "-", f"file not found ({tmp_path / 'config_app.json'})") in found
    assert (".env", "BOOTSTRAP_ADMIN_EMAIL", "is still a placeholder value") in found
    assert not any("email is not configured" in message for _, _, message in found)

    (tmp_path / "config_app.json").write_text(
        json.dumps({**GOOD_CONFIG, "port": 99999, "mcp_server_url": "ftp://x", "usage": {"weekly_token_limit": -1}}),
        encoding="utf-8",
    )
    with (tmp_path / ".env").open("a", encoding="utf-8") as env_file:
        env_file.write("SMTP_PASSWORD=hunter2\nSMTP_PORT=abc\n")
    (tmp_path / "config_agents.json").write_text(
        json.dumps({"agents": [{"id": "a", "label": "A", "url": "http://a/mcp"}, {"id": "a", "label": "", "url": "nope"}]}),
        encoding="utf-8",
    )

    found = issues(client)
    assert {i for i in found if i[0] == "config_app.json"} == {
        ("config_app.json", "port", "must be a port number (1-65535)"),
        ("config_app.json", "mcp_server_url", "must be an http(s) URL"),
        ("config_app.json", "usage.weekly_token_limit", "must be a whole number, 0 or more (0 = unlimited)"),
        # The test app runs with backups off.
        ("config_app.json", "backup.enabled", "is false: the database is not backed up automatically"),
    }
    assert {i[1:] for i in found if i[0].startswith("agents registry")} == {
        ("agents[1].label", "must be a non-empty string"),
        ("agents[1].url", "must be an http(s) URL"),
        ("agents[1].id", "duplicate agent id"),
    }
    smtp = {i[1:] for i in found if i[0] == ".env"}
    assert not any(key.startswith("SMTP_") or key == "MAIL_FROM_ADDRESS" for key, _ in smtp)
    # A secret's value never appears in a message.
    assert not any("hunter2" in part for issue in found for part in issue)


def test_issues_carry_a_severity(client: TestClient, tmp_path: Path) -> None:
    as_admin(client)
    (tmp_path / "config_app.json").write_text(json.dumps({**GOOD_CONFIG, "port": 99999}), encoding="utf-8")

    levels = {(i["file"], i["key"]): i["severity"] for i in client.get("/api/config-issues").json()}

    assert levels[("config_app.json", "port")] == "error"
    assert levels[("config_app.json", "backup.enabled")] == "warning"
    assert levels[(".env", "BOOTSTRAP_ADMIN_EMAIL")] == "warning"
    assert (".env", "-") not in levels  # No local SMTP setup warning.


def test_config_issues_need_permission(client: TestClient, email: FakeEmailSender) -> None:
    assert client.get("/api/config-issues").status_code == 401
    make_member(client, email)
    login(client, "alice")
    assert client.get("/api/config-issues").status_code == 403


def test_a_missing_env_file_is_an_error(client: TestClient, tmp_path: Path) -> None:
    as_admin(client)
    (tmp_path / ".env").unlink()

    found = {(i["file"], i["key"], i["severity"]) for i in client.get("/api/config-issues").json()}

    assert (".env", "-", "error") in found


def test_a_registry_url_replaces_the_file_check(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    from dataclasses import replace

    import httpx

    from src.services import config_validation
    from tests.conftest import make_settings

    settings = replace(
        make_settings(tmp_path),
        agents_registry_path=tmp_path / "missing.json",
        agents_registry_url="http://agents.test/registry",
    )
    # No file read, so the missing file is not reported.
    assert not any(i.file.startswith("agents registry") for i in config_validation.collect_issues(settings))

    real = httpx.AsyncClient

    def serve(response: httpx.Response) -> None:
        monkeypatch.setattr(
            config_validation.httpx,
            "AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(lambda request: response), **kw),
        )

    serve(httpx.Response(200, json={"agents": [{"id": "a", "label": "A", "url": "nope"}]}))
    found = asyncio.run(config_validation.collect_issues_async(settings))
    assert [(i.file, i.key) for i in found if i.file.startswith("agents registry")] == [
        ("agents registry (URL)", "agents[0].url")
    ]

    serve(httpx.Response(401, json={"error": "no"}))
    found = asyncio.run(config_validation.collect_issues_async(settings))
    assert any(i.key == "agents_registry_url" and "could not be read" in i.message for i in found)


def test_emberlings_url_must_be_an_http_url(client: TestClient, tmp_path: Path) -> None:
    as_admin(client)
    (tmp_path / "config_app.json").write_text(
        json.dumps({**GOOD_CONFIG, "emberlings_url": "ftp://games"}), encoding="utf-8"
    )

    assert ("config_app.json", "emberlings_url", "must be an http(s) URL") in issues(client)


def test_emberlings_url_is_optional(monkeypatch, tmp_path: Path) -> None:
    import src.config as config

    monkeypatch.setattr(config, "CONFIGS_DIR", tmp_path)
    (tmp_path / "config_app.json").write_text(json.dumps({}), encoding="utf-8")
    assert config.load_settings().emberlings_url == config.DEFAULT_EMBERLINGS_URL == "http://127.0.0.1:8060"

    (tmp_path / "config_app.json").write_text(json.dumps({"emberlings_url": "http://10.0.0.9:8060"}), encoding="utf-8")
    assert config.load_settings().emberlings_url == "http://10.0.0.9:8060"
