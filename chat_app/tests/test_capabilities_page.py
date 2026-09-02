import urllib.error
from io import BytesIO
from unittest.mock import patch

from types import SimpleNamespace

from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, Permission, Role, db
from src.pages.__index__ import register_pages
from src.pages.Capabilities.__index__ import _group_resources_by_capability, _group_tools_by_capability
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

from pathlib import Path

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_capabilities_test_app(tmp_path):
    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'capabilities_test.db'}"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    app.config["SECRET_KEY"] = "test-secret"
    app.config["MAIL_SUPPRESS_SEND"] = True

    db.init_app(app)
    with app.app_context():
        db.create_all()

    init_login_manager(app)
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    init_mail(app, secrets_dir)
    register_pages(app)

    return app


def _create_account(app, username, permission_names):
    with app.app_context():
        account = Account(
            username=username,
            email=f"{username}@example.com",
            password_hash=generate_password_hash("pw"),
        )
        if permission_names:
            role = Role(name=f"{username}_role")
            db.session.add(role)
            for name in permission_names:
                permission = db.session.query(Permission).filter_by(name=name).first()
                if permission is None:
                    permission = Permission(name=name)
                    db.session.add(permission)
                role.permissions.append(permission)
            account.roles.append(role)
        db.session.add(account)
        db.session.commit()
        return account.id


def _login_as(client, account_id):
    with client.session_transaction() as flask_session:
        flask_session["_user_id"] = str(account_id)
        flask_session["_fresh"] = True


def test_capabilities_page_requires_authentication(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/capabilities/")

    assert response.status_code == 401


def test_capabilities_page_forbidden_without_either_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "nocapaccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/capabilities/")

    assert response.status_code == 403


def test_capabilities_page_renders_with_view_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capviewer", ["capabilities.view"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch("src.pages.Capabilities.__index__.list_tools", return_value=[]), \
         patch("src.pages.Capabilities.__index__.list_resource_templates", return_value=[]), \
         patch("src.pages.Capabilities.__index__.fetch_extensions", return_value=[]), \
         patch("src.pages.Capabilities.__index__.fetch_capabilities", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200


def test_try_tool_forbidden_with_only_view_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capviewonly", ["capabilities.view"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/capabilities/api/try/some_tool", json={})

    assert response.status_code == 403


def test_try_tool_allowed_with_try_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "captryer", ["capabilities.try"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch("src.pages.Capabilities.__index__.call_tool", return_value="ok result"):
        response = client.post("/capabilities/api/try/some_tool", json={})

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "result": "ok result"}


def test_api_tools_forbidden_with_only_try_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "captryonly", ["capabilities.try"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/capabilities/api/tools")

    assert response.status_code == 403


def test_toggle_capability_forbidden_with_only_try_permission(tmp_path):
    """capabilities.try grants running a tool with your own inputs, not
    changing what's available to every user - a different permission
    tier, so it must not also unlock the toggle route."""
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "captryonlytoggle", ["capabilities.try"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/capabilities/api/capabilities/otp/toggle", json={"enabled": False})

    assert response.status_code == 403


def test_toggle_capability_allowed_with_manage_permission(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capmanager", ["capabilities.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch(
        "src.pages.Capabilities.__index__.set_capability_enabled",
        return_value={"name": "otp", "enabled": False},
    ) as mock_set:
        response = client.post("/capabilities/api/capabilities/otp/toggle", json={"enabled": False})

    assert response.status_code == 200
    assert response.get_json() == {"name": "otp", "enabled": False}
    mock_set.assert_called_once_with("otp", False)


def test_toggle_capability_missing_enabled_field_is_400(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capmanagerbadbody", ["capabilities.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/capabilities/api/capabilities/otp/toggle", json={})

    assert response.status_code == 400


def test_toggle_capability_forwards_mcp_servers_404(tmp_path):
    """An unknown capability name is mcp_server's own 404, with its own
    message naming the capability - forwarded intact rather than
    collapsed into a generic error, same reasoning as
    Chat/__index__.py's _forward_extension_error."""
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capmanager404", ["capabilities.manage"])
    client = app.test_client()
    _login_as(client, account_id)

    error = urllib.error.HTTPError(
        url="http://127.0.0.1:8010/capabilities/nonexistent",
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=BytesIO(b'{"error": "Unknown capability \'nonexistent\'"}'),
    )

    with patch("src.pages.Capabilities.__index__.set_capability_enabled", side_effect=error):
        response = client.post("/capabilities/api/capabilities/nonexistent/toggle", json={"enabled": False})

    assert response.status_code == 404
    assert response.get_json() == {"error": "Unknown capability 'nonexistent'"}


def test_capabilities_page_has_no_inline_event_handlers(tmp_path):
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "cspuser", ["capabilities.view"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch("src.pages.Capabilities.__index__.list_tools", return_value=[]), \
         patch("src.pages.Capabilities.__index__.list_resource_templates", return_value=[]), \
         patch("src.pages.Capabilities.__index__.fetch_extensions", return_value=[]), \
         patch("src.pages.Capabilities.__index__.fetch_capabilities", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    assert b"onclick=" not in response.data
    assert b"onsubmit=" not in response.data
    assert b'style="display:none"' not in response.data


def test_capabilities_page_renders_an_enum_field_as_a_datalist_and_shows_the_default(tmp_path):
    """mcp_server's tool_suggestions.py injects `enum` into a parameter's
    schema, and FastMCP already puts `default` there for any optional
    parameter - this page must turn both into something a human sees,
    not silently drop them the way the old plain-text-input rendering did."""
    app = _build_capabilities_test_app(tmp_path)
    account_id = _create_account(app, "capviewer2", ["capabilities.view"])
    client = app.test_client()
    _login_as(client, account_id)

    tool = SimpleNamespace(
        name="get_host_health_tool",
        description="Check host health",
        inputSchema={
            "properties": {
                "name": {"type": "string", "enum": ["zima", "desktop"]},
                "verify_ssl": {"type": "boolean", "default": True},
            }
        },
    )

    with patch("src.pages.Capabilities.__index__.list_tools", return_value=[tool]), \
         patch("src.pages.Capabilities.__index__.list_resource_templates", return_value=[]), \
         patch("src.pages.Capabilities.__index__.fetch_extensions", return_value=[]), \
         patch("src.pages.Capabilities.__index__.fetch_capabilities", return_value=[]):
        response = client.get("/capabilities/")

    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert '<datalist id="get_host_health_tool-name-options">' in body
    assert '<option value="zima">' in body
    assert '<option value="desktop">' in body
    assert "(default: True)" in body


def _tool(name, extension_id=None):
    return {"name": name, "title": name, "description": "", "input_schema": {}, "extension_id": extension_id}


def _resource(name):
    return {"name": name, "title": name, "description": "", "uri_template": "", "params": []}


def test_group_tools_by_capability_carries_id_label_and_enabled_state():
    groups = _group_tools_by_capability(
        [_tool("get_host_health_tool")],
        {"host_health": {"enabled": False, "title": "Host Health", "tools": ["get_host_health_tool"]}},
    )

    assert groups == [
        {
            "id": "host_health",
            "label": "Host Health",
            "enabled": False,
            "toggleable": True,
            "tools": [_tool("get_host_health_tool")],
        }
    ]


def test_group_tools_by_capability_excludes_extension_tools():
    groups = _group_tools_by_capability([_tool("reference__echo", extension_id="reference")], {})

    assert groups == []


def test_group_tools_by_capability_defaults_to_enabled_when_mcp_server_state_is_unknown():
    """mcp_server unreachable (empty capabilities_meta) must not read as
    every capability being off - same "absent means enabled" default
    app_config.capability_enabled() uses on the mcp_server side."""
    groups = _group_tools_by_capability([_tool("get_host_health_tool")], {})

    assert groups[0]["enabled"] is True
    assert groups[0]["toggleable"] is False  # unknown state -> no switch, would just 404


def test_group_tools_by_capability_fallback_group_is_never_toggleable():
    groups = _group_tools_by_capability([_tool("some_future_tool")], {"other": {"enabled": True, "title": "Other"}})

    assert groups[0]["id"] == "other"
    assert groups[0]["toggleable"] is False


def test_group_resources_by_capability_carries_id_label_and_enabled_state():
    groups = _group_resources_by_capability(
        [_resource("host_health")],
        {"host_health": {"enabled": True, "title": "Host Health", "resources": ["host_health"]}},
    )

    assert groups == [
        {
            "id": "host_health",
            "label": "Host Health",
            "enabled": True,
            "toggleable": True,
            "resources": [_resource("host_health")],
        }
    ]


def test_group_tools_by_capability_keeps_a_disabled_capabilitys_group_with_no_tools():
    """The actual bug this seeding exists to prevent: mcp_server never
    registers a disabled capability's tools at all, so building groups
    purely from the live tool list would make a disabled capability's
    group vanish - taking the only switch that could turn it back on
    with it."""
    groups = _group_tools_by_capability([], {"host_health": {"enabled": False, "title": "Host Health"}})

    assert groups == [
        {"id": "host_health", "label": "Host Health", "enabled": False, "toggleable": True, "tools": []}
    ]


def test_group_resources_by_capability_keeps_a_disabled_capabilitys_group_with_no_resources():
    groups = _group_resources_by_capability(
        [], {"host_health": {"enabled": False, "title": "Host Health", "resources": ["host_health"]}}
    )

    assert groups == [
        {"id": "host_health", "label": "Host Health", "enabled": False, "toggleable": True, "resources": []}
    ]


def test_group_resources_by_capability_does_not_seed_a_group_for_a_tool_only_capability():
    """"otp" owns no resource, so it must not get an empty, pointless
    resource-section group just because it's a known, enabled
    capability - only "host_health" (which owns one) should seed here."""
    groups = _group_resources_by_capability(
        [],
        {
            "host_health": {"enabled": True, "title": "Host Health", "resources": ["host_health"]},
            "otp": {"enabled": True, "title": "OTP", "resources": []},
        },
    )

    assert [group["id"] for group in groups] == ["host_health"]
