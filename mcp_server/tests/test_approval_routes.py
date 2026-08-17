"""Tests for the approval HTTP routes.

The property that matters most here is that GET does nothing. Links in
email are fetched by machines - mail scanners checking for malware, chat
clients building previews - so a GET with side effects would mean those
machines can approve things.
"""

from __future__ import annotations

import warnings
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.applications import Starlette

warnings.filterwarnings("ignore", category=DeprecationWarning)
from starlette.testclient import TestClient  # noqa: E402

from mcp_server import config  # noqa: E402
from mcp_server.approval_routes import install_approval_routes  # noqa: E402
from mcp_server.infra import approvals, pending_requests  # noqa: E402


@pytest.fixture
def ran():
    return []


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    """Point the routes at a throwaway database.

    The handlers are driven by a browser, so there's no caller to pass a
    path in - they read ``settings.pending_requests_path``. Settings is a
    frozen dataclass, so this swaps in a modified copy rather than
    assigning to the field. Both modules need it: the route reads the
    path to look a request up, and approvals.approve() reads it again to
    claim and execute.
    """
    path = tmp_path / "pending.db"
    patched = replace(config.settings, pending_requests_path=path)
    monkeypatch.setattr("mcp_server.approval_routes.settings", patched)
    monkeypatch.setattr("mcp_server.infra.approvals.settings", patched)
    return path


@pytest.fixture
def client(db, ran):
    with patch.dict(approvals._REGISTRY, {}, clear=True):
        approvals.register(
            approvals.GatedCapability(
                name="restart_service",
                summarize=lambda p: f"Restart {p['service']}",
                execute=lambda p: ran.append(p) or f"restarted {p['service']}",
            )
        )
        app = Starlette()
        install_approval_routes(app)
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def token(db):
    return pending_requests.create(db, "restart_service", {"service": "nginx"})


# --- GET is inert ------------------------------------------------------


def test_get_shows_the_request_without_running_it(client, token, ran, db):
    response = client.get(f"/approvals/{token}")

    assert response.status_code == 200
    assert "Restart nginx" in response.text
    assert ran == []
    assert pending_requests.get(db, token).status == "pending"


def test_get_repeated_still_runs_nothing(client, token, ran):
    """A mail scanner may fetch the link several times."""
    for _ in range(3):
        client.get(f"/approvals/{token}")

    assert ran == []


def test_get_offers_a_form_rather_than_a_plain_link(client, token):
    """Approval has to require a POST; a link would be followable by
    anything that crawls the message."""
    body = client.get(f"/approvals/{token}").text

    assert 'method="post"' in body.lower()


# --- POST executes -----------------------------------------------------


def test_post_executes_and_reports(client, token, ran):
    response = client.post(f"/approvals/{token}", data={"approved_by": "alice"})

    assert response.status_code == 200
    assert "restarted nginx" in response.text
    assert ran == [{"service": "nginx"}]


def test_post_twice_executes_once(client, token, ran):
    client.post(f"/approvals/{token}", data={"approved_by": "alice"})
    second = client.post(f"/approvals/{token}", data={"approved_by": "alice"})

    assert second.status_code == 409
    assert len(ran) == 1


def test_post_records_the_approver(client, token, db):
    client.post(f"/approvals/{token}", data={"approved_by": "alice"})

    assert pending_requests.get(db, token).approved_by == "alice"


def test_post_that_fails_during_execution_does_not_leak_exception_text(db, ran, log_dir):
    """execute() can raise after the request is already claimed (see
    approvals.approve's docstring). The failure page used to embed
    str(error) directly - readable by anyone who clicks the emailed
    link, not just the developer who wrote the code that raised."""
    boom = RuntimeError("connect failed: postgres://admin:hunter2@10.0.0.5:5432")
    with patch.dict(approvals._REGISTRY, {}, clear=True):
        approvals.register(
            approvals.GatedCapability(
                name="explode",
                summarize=lambda p: "Explode",
                execute=lambda p: (_ for _ in ()).throw(boom),
            )
        )
        app = Starlette()
        install_approval_routes(app)
        token = pending_requests.create(db, "explode", {})
        with TestClient(app) as client:
            response = client.post(f"/approvals/{token}", data={"approved_by": "alice"})

    assert response.status_code == 500
    assert "hunter2" not in response.text
    assert "reference" in response.text.lower()


# --- bad states --------------------------------------------------------


def test_unknown_token_is_a_404(client, ran):
    assert client.get("/approvals/nope").status_code == 404
    assert ran == []


def test_already_handled_request_is_a_409(client, token):
    client.post(f"/approvals/{token}", data={"approved_by": "alice"})

    response = client.get(f"/approvals/{token}")

    assert response.status_code == 409
    assert "already approved" in response.text.lower()


def test_expired_request_is_a_410(client, db, ran):
    expired = pending_requests.create(db, "restart_service", {"service": "nginx"}, ttl_hours=-1)

    assert client.get(f"/approvals/{expired}").status_code == 410
    assert client.post(f"/approvals/{expired}", data={"approved_by": "alice"}).status_code == 409
    assert ran == []


def test_request_for_a_capability_that_no_longer_exists(client, db):
    """A pending row outlives a deploy that removed its capability."""
    orphan = pending_requests.create(db, "gone_away", {})

    response = client.get(f"/approvals/{orphan}")

    assert response.status_code == 409
    assert "no longer offers" in response.text


# --- output escaping ---------------------------------------------------


def test_payload_is_escaped_on_the_page(client, db):
    """Payload values came from the model, which may be echoing hostile
    text. A page that the thing being approved can restyle is worse than
    no page."""
    nasty = pending_requests.create(db, "restart_service", {"service": "<script>alert(1)</script>"})

    body = client.get(f"/approvals/{nasty}").text

    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_page_loads_nothing_external(client, token):
    """No CDN, no external anything - the token is in this URL, and an
    outbound request would put it in a Referer header."""
    body = client.get(f"/approvals/{token}").text

    assert "http://" not in body.replace('http://www.w3.org', '')
    assert "https://" not in body
