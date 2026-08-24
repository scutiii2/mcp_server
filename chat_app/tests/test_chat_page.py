import dataclasses
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, LogEntry, Permission, Role, db
from src.pages.__index__ import register_pages
from src.pages.Chat import __index__ as chat_index
from src.services import commands
from src.services.auth_service import init_login_manager
from src.services.email_service import init_mail

from pathlib import Path

_SHARED_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "pages" / "__shared__"


def _build_chat_test_app(tmp_path, monkeypatch):
    # Isolate chats_db_path per test - src.services.llm.settings.settings
    # is a module-level singleton (see Task 1), and this test never goes
    # through run.py's create_app() (which is what resolves it against
    # BASE_DIR), so without this every test in this file would share one
    # real, un-isolated data/chats.db relative to wherever pytest's cwd
    # happens to be - the same dataclasses.replace + monkeypatch.setattr
    # pattern MCPArchitecture's own conftest.py used for this exact
    # problem (its chats_db fixture).
    monkeypatch.setattr(
        chat_index, "settings", dataclasses.replace(chat_index.settings, chats_db_path=tmp_path / "chats.db")
    )

    app = Flask(
        __name__,
        template_folder=str(_SHARED_TEMPLATES_DIR),
        static_folder=str(_SHARED_TEMPLATES_DIR),
        static_url_path="/shared/static",
    )
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'chat_test.db'}"
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


def test_chat_page_requires_authentication(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    client = app.test_client()

    response = client.get("/chat/")

    assert response.status_code == 401


def test_chat_page_forbidden_without_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nochataccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/")

    assert response.status_code == 403


def test_chat_page_renders_with_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "chatuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/")

    assert response.status_code == 200
    assert b"chat-history-list" in response.data


def test_chat_api_requires_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nochatapi", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/chat/api/chat", json={"question": "hi"})

    assert response.status_code == 403


def test_chat_api_persists_chat_trace_log_entry_on_success(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "traceuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    from src.services.llm.base import ChatResult

    fake_result = ChatResult(response="hello back", provider_id="openai", model="gpt-5.6-sol", total_tokens=42)
    with patch.object(chat_index.router, "run_chat", return_value=fake_result):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    with app.app_context():
        traces = db.session.query(LogEntry).filter_by(kind="chat_trace", account_id=account_id).all()
        assert len(traces) == 1
        assert "hi" in traces[0].message


def test_chat_api_unexpected_error_produces_log_entry_and_safe_response(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "erroruser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index.router, "run_chat", side_effect=RuntimeError("boom")):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    assert "boom" not in response.get_json()["response"]
    with app.app_context():
        errors = db.session.query(LogEntry).filter_by(kind="error", account_id=account_id).all()
        assert len(errors) == 1
        assert "boom" in errors[0].details


def test_chat_api_command_input_never_calls_the_llm_router(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "commanduser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index, "commands") as fake_commands, patch.object(
        chat_index.router, "run_chat"
    ) as fake_run_chat:
        fake_commands.execute_command.return_value = "OTP sent."
        response = client.post("/chat/api/chat", json={"question": "/otp get_otp", "history": []})

    assert response.status_code == 200
    body = response.get_json()
    assert body["response"] == "OTP sent."
    assert body["kind"] == "command"
    fake_run_chat.assert_not_called()
    fake_commands.execute_command.assert_called_once_with("/otp get_otp", [])


def test_chat_api_non_command_input_still_uses_the_llm_router(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "noncommanduser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    from src.services.llm.base import ChatResult

    fake_result = ChatResult(response="hi back", provider_id="openai", model="gpt-5.6-sol")
    with patch.object(chat_index.router, "run_chat", return_value=fake_result) as fake_run_chat:
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    body = response.get_json()
    assert body["kind"] == "assistant"
    fake_run_chat.assert_called_once()


def test_commands_api_returns_the_registry_as_json(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "commandsapiuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    fake_registry = {
        "otp": {
            "get_otp": commands.RegisteredCommand(
                capability="otp",
                name="get_otp",
                description="generate otp",
                tool_name="request_otp_tool",
                params=[
                    commands.CommandParam(
                        name="recipient", required=False, type="string", has_default=True, default="ops@example.com"
                    )
                ],
            )
        }
    }
    with patch.object(chat_index.commands, "build_command_registry", return_value=fake_registry) as fake_build:
        response = client.get("/chat/api/commands?enabled_extensions=reference,other")

    assert response.status_code == 200
    assert response.get_json() == {
        "otp": {
            "get_otp": {
                "description": "generate otp",
                "params": [
                    {
                        "name": "recipient",
                        "required": False,
                        "type": "string",
                        "has_default": True,
                        "default": "ops@example.com",
                        "enum": None,
                    }
                ],
            }
        }
    }
    fake_build.assert_called_once_with(["reference", "other"])


def test_commands_api_includes_a_params_enum_when_the_registry_has_one(tmp_path, monkeypatch):
    """mcp_server's tool_suggestions.py puts an `enum` in a param's schema,
    and commands.py's _params_from_schema carries it into CommandParam -
    this route must forward it too, or the Chat page's slash-command
    autocomplete has nothing to offer for a value suggestion."""
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "commandsapienum", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    fake_registry = {
        "host_health": {
            "get_host_health": commands.RegisteredCommand(
                capability="host_health",
                name="get_host_health",
                description="Check host health",
                tool_name="get_host_health_tool",
                params=[
                    commands.CommandParam(name="name", required=True, type="string", enum=["zima", "desktop"]),
                ],
            )
        }
    }
    with patch.object(chat_index.commands, "build_command_registry", return_value=fake_registry):
        response = client.get("/chat/api/commands")

    params = response.get_json()["host_health"]["get_host_health"]["params"]
    assert params == [
        {"name": "name", "required": True, "type": "string", "has_default": False, "default": None,
         "enum": ["zima", "desktop"]}
    ]


def test_commands_api_requires_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nocommandsapiaccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/api/commands")

    assert response.status_code == 403


def test_chat_page_has_no_inline_event_handlers(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "cspuser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/")

    assert response.status_code == 200
    assert b"onclick=" not in response.data
