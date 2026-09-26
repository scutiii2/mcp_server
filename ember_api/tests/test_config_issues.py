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
    # conftest's files: no config_app.json, an example.com admin, no SMTP file.
    assert ("config_app.json", "-", f"file not found ({tmp_path / 'config_app.json'})") in found
    assert ("secret_bootstrap_admin.env", "BOOTSTRAP_ADMIN_EMAIL", "is still a placeholder value") in found
    assert ("secret_smtp.env", "-", "file is missing (copy it from its .example)") in found

    (tmp_path / "config_app.json").write_text(
        json.dumps({**GOOD_CONFIG, "port": 99999, "mcp_server_url": "ftp://x", "usage": {"weekly_token_limit": -1}}),
        encoding="utf-8",
    )
    (tmp_path / "secrets" / "secret_smtp.env").write_text("SMTP_PASSWORD=hunter2\nSMTP_PORT=abc\n", encoding="utf-8")
    (tmp_path / "config_agents.json").write_text(
        json.dumps({"agents": [{"id": "a", "label": "A", "url": "http://a/mcp"}, {"id": "a", "label": "", "url": "nope"}]}),
        encoding="utf-8",
    )

    found = issues(client)
    assert {i for i in found if i[0] == "config_app.json"} == {
        ("config_app.json", "port", "must be a port number (1-65535)"),
        ("config_app.json", "mcp_server_url", "must be an http(s) URL"),
        ("config_app.json", "usage.weekly_token_limit", "must be a whole number, 0 or more (0 = unlimited)"),
    }
    assert {i[1:] for i in found if i[0].startswith("agents registry")} == {
        ("agents[1].label", "must be a non-empty string"),
        ("agents[1].url", "must be an http(s) URL"),
        ("agents[1].id", "duplicate agent id"),
    }
    smtp = {i[1:] for i in found if i[0] == "secret_smtp.env"}
    assert ("SMTP_HOST", "is empty but other SMTP settings are set") in smtp
    assert ("SMTP_PORT", "must be a port number (1-65535)") in smtp
    # A secret's value never appears in a message.
    assert not any("hunter2" in part for issue in found for part in issue)


def test_config_issues_need_permission(client: TestClient, email: FakeEmailSender) -> None:
    assert client.get("/api/config-issues").status_code == 401
    make_member(client, email)
    login(client, "alice")
    assert client.get("/api/config-issues").status_code == 403
