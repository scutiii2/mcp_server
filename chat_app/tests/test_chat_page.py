import dataclasses
import io
import json
from unittest.mock import ANY, patch

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
        chat_index,
        "settings",
        dataclasses.replace(
            chat_index.settings,
            chats_db_path=tmp_path / "chats.db",
            attachments_dir=tmp_path / "attachments",
        ),
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


def _set_attachments_config(tmp_path, monkeypatch, max_file_size_mb=5):
    config_path = tmp_path / "config_attachments.json"
    config_path.write_text(json.dumps({"max_file_size_mb": max_file_size_mb}), encoding="utf-8")
    monkeypatch.setattr(
        chat_index, "settings", dataclasses.replace(chat_index.settings, attachments_config_path=config_path)
    )


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
                        "format": None,
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
         "enum": ["zima", "desktop"], "format": None}
    ]


def test_commands_api_requires_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nocommandsapiaccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/api/commands")

    assert response.status_code == 403


def test_upload_attachment_creates_a_new_chat_when_none_given(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    _set_attachments_config(tmp_path, monkeypatch)
    account_id = _create_account(app, "uploaduser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/chat/api/attachments",
        data={"file": (io.BytesIO(b"hello world"), "notes.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["filename"] == "notes.txt"
    assert body["size"] == 11
    assert body["chat_id"]

    from src.services import chats_store
    assert chats_store.get_chat(chat_index.settings.chats_db_path, "uploaduser", body["chat_id"]) is not None


def test_upload_attachment_into_an_existing_chat(tmp_path, monkeypatch):
    from src.services import chats_store

    app = _build_chat_test_app(tmp_path, monkeypatch)
    _set_attachments_config(tmp_path, monkeypatch)
    account_id = _create_account(app, "uploaduser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    existing_id = chats_store.save_chat(chat_index.settings.chats_db_path, "uploaduser2", None, [])

    response = client.post(
        "/chat/api/attachments",
        data={"file": (io.BytesIO(b"data"), "a.txt"), "chat_id": existing_id},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.get_json()["chat_id"] == existing_id


def test_upload_attachment_rejects_a_file_over_the_configured_size_limit(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    _set_attachments_config(tmp_path, monkeypatch, max_file_size_mb=0.00001)
    account_id = _create_account(app, "uploaduser3", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/chat/api/attachments",
        data={"file": (io.BytesIO(b"this is definitely more than ten bytes"), "big.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_upload_attachment_rejects_a_non_utf8_file(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    _set_attachments_config(tmp_path, monkeypatch)
    account_id = _create_account(app, "uploaduser4", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/chat/api/attachments",
        data={"file": (io.BytesIO(b"\xff\xfe\x00\x01"), "binary.dat")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400


def test_list_and_delete_attachments_round_trip(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    _set_attachments_config(tmp_path, monkeypatch)
    account_id = _create_account(app, "listuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    upload = client.post(
        "/chat/api/attachments",
        data={"file": (io.BytesIO(b"hello"), "a.txt")},
        content_type="multipart/form-data",
    )
    chat_id = upload.get_json()["chat_id"]

    listing = client.get(f"/chat/api/chats/{chat_id}/attachments")
    assert listing.get_json() == [{"filename": "a.txt", "size": 5}]

    deletion = client.delete(f"/chat/api/chats/{chat_id}/attachments/a.txt")
    assert deletion.status_code == 204

    listing_after = client.get(f"/chat/api/chats/{chat_id}/attachments")
    assert listing_after.get_json() == []


def test_delete_attachment_for_an_unknown_filename_is_not_found(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    _set_attachments_config(tmp_path, monkeypatch)
    account_id = _create_account(app, "deleteuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    upload = client.post(
        "/chat/api/attachments",
        data={"file": (io.BytesIO(b"hello"), "a.txt")},
        content_type="multipart/form-data",
    )
    chat_id = upload.get_json()["chat_id"]

    response = client.delete(f"/chat/api/chats/{chat_id}/attachments/nope.txt")

    assert response.status_code == 404


def test_list_attachments_for_another_users_chat_is_not_found(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    _set_attachments_config(tmp_path, monkeypatch)
    owner_id = _create_account(app, "owner", ["chat.access"])
    intruder_id = _create_account(app, "intruder", ["chat.access"])
    owner_client = app.test_client()
    _login_as(owner_client, owner_id)
    upload = owner_client.post(
        "/chat/api/attachments",
        data={"file": (io.BytesIO(b"secret"), "s.txt")},
        content_type="multipart/form-data",
    )
    chat_id = upload.get_json()["chat_id"]

    intruder_client = app.test_client()
    _login_as(intruder_client, intruder_id)
    response = intruder_client.get(f"/chat/api/chats/{chat_id}/attachments")

    assert response.status_code == 404


def test_attachments_endpoints_require_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    _set_attachments_config(tmp_path, monkeypatch)
    account_id = _create_account(app, "noaccessuser", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/chat/api/attachments",
        data={"file": (io.BytesIO(b"hi"), "a.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 403


def test_deleting_a_chat_also_deletes_its_attachments(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    _set_attachments_config(tmp_path, monkeypatch)
    account_id = _create_account(app, "deletechatuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    upload = client.post(
        "/chat/api/attachments",
        data={"file": (io.BytesIO(b"hello"), "a.txt")},
        content_type="multipart/form-data",
    )
    chat_id = upload.get_json()["chat_id"]

    response = client.delete(f"/chat/api/chats/{chat_id}")

    assert response.status_code == 204
    assert not (chat_index.settings.attachments_dir / chat_id).exists()


def test_chat_api_command_turns_ignore_the_attachments_field(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "commandattachuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index, "commands") as fake_commands, patch.object(
        chat_index.attachments_store, "read_attachment_text"
    ) as fake_read_text:
        fake_commands.execute_command.return_value = "OTP sent."
        response = client.post(
            "/chat/api/chat",
            json={"question": "/otp get_otp", "history": [], "attachments": ["notes.txt"]},
        )

    assert response.status_code == 200
    fake_read_text.assert_not_called()


def test_chat_page_includes_attachment_ui_elements(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "attachuiuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/")

    assert response.status_code == 200
    assert b'id="attach-btn"' in response.data
    assert b'id="attach-input"' in response.data
    assert b'id="staged-attachments"' in response.data


def test_chat_page_has_no_inline_event_handlers(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "cspuser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/")

    assert response.status_code == 200
    assert b"onclick=" not in response.data
