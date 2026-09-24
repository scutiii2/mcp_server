import dataclasses
import io
import json
import threading
import pytest
from datetime import datetime
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from src.models import Account, LogEntry, Permission, Role, db
from src.pages.__index__ import register_pages
# Configuration files are deployment-local and absent in isolated worktrees.
with patch("src.utils.config_loader.load_json_config", return_value={
    "six_hour_token_limit": 1_000_000,
    "weekly_token_limit": 5_000_000,
    "max_context_tokens_per_chat": 150_000,
}):
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
        chat_index, "settings", dataclasses.replace(
            chat_index.settings, chats_db_path=tmp_path / "chats.db", usage_db_path=tmp_path / "usage.db"
        )
    )
    agents = [
        {"id": "claude-agent", "label": "Claude Agent", "url": "http://127.0.0.1:9100/mcp"},
        {"id": "openai-agent", "label": "OpenAI Agent", "url": "http://127.0.0.1:9101/mcp"},
    ]
    monkeypatch.setattr(chat_index.agent_registry, "_AGENTS", agents)
    monkeypatch.setattr(chat_index.agent_registry, "_AGENTS_BY_ID", {agent["id"]: agent for agent in agents})

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


def _read_sse_events(response):
    """chat_api() now streams SSE frames (see Task 6's services/sse.py)
    instead of one JSON body - this decodes the `data: {...}\n\n` frames
    back into the event dicts the old response.get_json() callers here
    used to assert on directly. events[-1] is always the terminal
    final/error event; chat_api's own generate() converts an upstream
    error event into a final event before it ever reaches the client, so
    an error case is asserted via events[-1] too, same as any other."""
    body = response.get_data(as_text=True)
    events = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if frame.startswith("data: "):
            events.append(json.loads(frame[len("data: "):]))
    return events


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
    assert b'id="chat-sidebar"' in response.data
    assert b'id="chat-sidebar-list"' in response.data
    assert b'id="manage-chats-view"' in response.data
    assert b'id="chat-main-view"' in response.data
    assert b'aria-label="Collapse chat list"' in response.data
    assert b'title="Collapse chat list"' in response.data


def test_chat_sidebar_static_contract_reserves_action_slot_and_syncs_toggle_label():
    chat_dir = Path(__file__).resolve().parents[1] / "src" / "pages" / "Chat"
    script = (chat_dir / "script.js").read_text(encoding="utf-8")
    styles = (chat_dir / "styles.css").read_text(encoding="utf-8")

    assert "toggle.setAttribute('aria-label', toggleLabel);" in script
    assert "actionSlot.className = 'chat-history-row-action-slot';" in script
    assert ".chat-history-row-action-slot {" in styles
    assert ".chat-history-controls::before" not in styles


def test_chat_client_conversation_management_contract_is_present():
    """Keep the client-only concurrency and sidebar helpers from regressing.

    Browser integration tests are outside this focused Flask suite, so this
    deliberately verifies the stable public helper names and human-facing
    relative-time labels that the page depends on.
    """
    script = (Path(__file__).resolve().parents[1] / "src" / "pages" / "Chat" / "script.js").read_text(encoding="utf-8")

    for helper in ("openChat", "startChatJob", "subscribeToChat", "renderChatHistory", "showManageChats", "sortChatRows"):
        assert f"function {helper}" in script or f"async function {helper}" in script
    assert "const chatStates = new Map()" in script
    assert "background: true" in script
    assert "Just now" in script
    assert "`${diffMinutes}m ago`" in script
    assert "return 'Yesterday'" in script
    assert "leftRunning !== rightRunning" in script
    assert "actionSlot.removeAttribute('aria-hidden')" in script


def test_chat_api_requires_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nochatapi", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/chat/api/chat", json={"question": "hi"})

    assert response.status_code == 403


def test_delete_selected_chats_api_deletes_only_the_signed_in_users_selection(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "batchdelete", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    db_path = chat_index.settings.chats_db_path
    first = chat_index.chats_store.save_chat(db_path, "batchdelete", None, [{"role": "user", "content": "first"}])
    second = chat_index.chats_store.save_chat(db_path, "batchdelete", None, [{"role": "user", "content": "second"}])
    other_user = chat_index.chats_store.save_chat(db_path, "other", None, [{"role": "user", "content": "private"}])

    response = client.delete("/chat/api/chats", json={"chat_ids": [first, second, other_user]})

    assert response.status_code == 200
    assert response.get_json() == {"deleted": 2}
    assert chat_index.chats_store.get_chat(db_path, "batchdelete", first) is None
    assert chat_index.chats_store.get_chat(db_path, "batchdelete", second) is None
    assert chat_index.chats_store.get_chat(db_path, "other", other_user) is not None


def test_delete_selected_chats_api_rejects_an_empty_or_malformed_selection(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "invalidbatchdelete", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    assert client.delete("/chat/api/chats", json={"chat_ids": []}).status_code == 400
    assert client.delete("/chat/api/chats", json={"chat_ids": "not-a-list"}).status_code == 400


def test_chat_api_persists_chat_trace_log_entry_on_success(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "traceuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        yield {"type": "final", "response": "hello back", "tools_used": ["server_note_lookup"], "tool_calls": [],
               "provider_id": "openai", "model": "gpt-5.6-sol", "total_tokens": 42,
               "context_tokens": 128, "context_window": 8192, "cancelled": False}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    final = _read_sse_events(response)[-1]
    # Full field-parity assertion (see plan's Global Constraints): every
    # field the SSE terminal event is documented to carry, not just a
    # subset - so a regression dropping any one of these is caught here.
    assert final["type"] == "final"
    assert final["response"] == "hello back"
    assert final["tools_used"] == ["server_note_lookup"]
    assert final["provider_id"] == "openai"
    assert final["model"] == "gpt-5.6-sol"
    assert final["total_tokens"] == 42
    assert final["context_tokens"] == 128
    assert final["context_window"] == 8192
    assert isinstance(final["elapsed_seconds"], (int, float))
    assert final["elapsed_seconds"] >= 0
    assert final["chat_id"] is not None
    assert final["kind"] == "assistant"
    with app.app_context():
        traces = db.session.query(LogEntry).filter_by(kind="chat_trace", account_id=account_id).all()
        assert len(traces) == 1
        assert "hi" in traces[0].message


def test_chat_api_persists_the_times_messages_were_sent(tmp_path, monkeypatch):
    """A completed turn keeps displayable, timezone-aware send times."""
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "timestampuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        yield {"type": "final", "response": "hello back", "cancelled": False}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert _read_sse_events(response)[-1]["response"] == "hello back"
    chat_id = _read_sse_events(response)[-1]["chat_id"]
    saved_chat = client.get(f"/chat/api/chats/{chat_id}").get_json()
    user_sent_at = saved_chat["messages"][0]["sent_at"]
    assistant_sent_at = saved_chat["messages"][1]["sent_at"]

    assert saved_chat["messages"][0]["role"] == "user"
    assert datetime.fromisoformat(user_sent_at).tzinfo is not None
    assert saved_chat["messages"][1]["role"] == "assistant"
    assert datetime.fromisoformat(assistant_sent_at).tzinfo is not None


def test_chat_api_saves_tool_steps_on_the_assistant_message(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "stepsuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        yield {"type": "step_start", "id": "1", "tool": "tool_server_list", "label": "Listing servers",
               "arguments": {"system_name": "s4h-demo"}}
        yield {"type": "step_end", "id": "1", "ok": True, "result": "x" * 5000}
        yield {"type": "step_start", "id": "2", "tool": "tool_server_restart", "label": "",
               "arguments": {"system_name": "s4h-demo"}}
        yield {"type": "step_end", "id": "2", "ok": False, "result": "boom"}
        yield {"type": "final", "response": "done", "cancelled": False}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    chat_id = _read_sse_events(response)[-1]["chat_id"]
    steps = client.get(f"/chat/api/chats/{chat_id}").get_json()["messages"][1]["steps"]

    assert [s["tool"] for s in steps] == ["tool_server_list", "tool_server_restart"]
    assert steps[0]["ok"] is True and steps[1]["ok"] is False
    assert steps[0]["label"] == "Listing servers"
    assert steps[0]["arguments"] == {"system_name": "s4h-demo"}
    assert len(steps[0]["result"]) == chat_index._STEP_RESULT_MAX


def test_chat_api_relays_step_and_token_events_before_the_final_event(tmp_path, monkeypatch):
    # Every other fake_ask_stream in this file yields only a terminal
    # final/error event, so nothing exercises event_source()'s plain
    # `yield event` passthrough for step_start/step_end/token - the route
    # could stop relaying those unmodified and every other test here would
    # still pass. This proves the four intermediate events survive the
    # route unmodified, in order, ahead of the terminal event.
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "traceevents", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        yield {"type": "step_start", "id": "1", "tool": "tool_server_start", "label": "Checking server status",
               "arguments": {"system_name": "s4e"}}
        yield {"type": "step_end", "id": "1", "ok": True, "result": "RUNNING at 42%"}
        yield {"type": "token", "text": "The "}
        yield {"type": "token", "text": "system is running."}
        yield {"type": "final", "response": "The system is running.", "tools_used": ["tool_server_start"],
               "tool_calls": [], "provider_id": "anthropic", "model": "claude-sonnet-5", "total_tokens": 50,
               "cancelled": False}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "is s4e done?", "history": []})

    assert response.status_code == 200
    events = _read_sse_events(response)
    events = [{key: value for key, value in event.items() if key not in {"sequence", "request_id"}}
              for event in events]
    assert events[0] == {"type": "step_start", "id": "1", "tool": "tool_server_start",
                          "label": "Checking server status", "arguments": {"system_name": "s4e"}}
    assert events[1] == {"type": "step_end", "id": "1", "ok": True, "result": "RUNNING at 42%"}
    assert events[2] == {"type": "token", "text": "The "}
    assert events[3] == {"type": "token", "text": "system is running."}
    assert events[-1]["type"] == "final"
    assert events[-1]["response"] == "The system is running."


def test_chat_api_unexpected_error_produces_log_entry_and_safe_response(tmp_path, monkeypatch):
    # ask_stream's own run() (see ai_agent_client.py) tags a genuinely
    # unplanned failure with "unplanned": True in the error event it puts
    # on the queue, distinguishing it from an agent-authored isError
    # result (see test_chat_api_agent_tool_error_shown_verbatim below,
    # which has no such key). This fake stands in for ask_stream itself,
    # so it yields the event shape ask_stream would actually produce
    # rather than raising directly - raising here would instead be caught
    # by stream_async_generator's own defense-in-depth catch-all (see
    # services/sse.py), which is a distinct, narrower bridging-bug path
    # and does not carry the "unplanned" marker.
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "erroruser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        yield {"type": "error", "message": "boom", "unplanned": True}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    final = _read_sse_events(response)[-1]
    assert final["response"] == "❌ Something went wrong while answering your question. Check the Logs page (Errors tab) for details."
    with app.app_context():
        errors = db.session.query(LogEntry).filter_by(kind="error", account_id=account_id).all()
        assert len(errors) == 1
        assert "boom" in errors[0].details


def test_chat_api_agent_tool_error_shown_verbatim(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "ratelimiteduser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        yield {"type": "error", "message": "claude is rate-limited right now - try again in 42s"}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert response.status_code == 200
    final = _read_sse_events(response)[-1]
    assert final["response"] == "❌ claude is rate-limited right now - try again in 42s"
    with app.app_context():
        # The verbatim/agent-authored path has no "unplanned" marker on its
        # error event (see test_chat_api_unexpected_error_produces_log_entry_
        # and_safe_response above), and per event_source()'s handling of a
        # non-unplanned error event, it must NOT write a LogEntry - mirroring
        # that sibling test's assertion of exactly one row for the opposite
        # (unplanned) path.
        errors = db.session.query(LogEntry).filter_by(kind="error", account_id=account_id).all()
        assert len(errors) == 0


def test_chat_api_command_input_never_calls_the_agent(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "commanduser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index, "commands") as fake_commands, patch.object(
        chat_index.ai_agent_client, "ask_stream"
    ) as fake_ask:
        fake_commands.execute_command.return_value = "OTP sent."
        response = client.post("/chat/api/chat", json={"question": "/otp get_otp", "history": []})

    assert response.status_code == 200
    body = _read_sse_events(response)[-1]
    assert body["response"] == "OTP sent."
    assert body["kind"] == "command"
    fake_ask.assert_not_called()
    fake_commands.execute_command.assert_called_once()
    assert fake_commands.execute_command.call_args.args == ("/otp get_otp", [])
    assert "agent_id" not in fake_commands.execute_command.call_args.kwargs


def test_chat_api_command_streams_tool_progress_before_the_final_result(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "progressuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    def slow_command(question, enabled_extensions, user=None, on_progress=None):
        on_progress("Connecting to host...")
        on_progress("Reading server.log...")
        return "Server status"

    with patch.object(chat_index.commands, "execute_command", slow_command):
        response = client.post("/chat/api/chat", json={"question": "/server list", "history": []})

    events = _read_sse_events(response)
    assert [e["type"] for e in events] == ["progress", "progress", "final"]
    assert [e["message"] for e in events[:2]] == ["Connecting to host...", "Reading server.log..."]
    assert events[-1]["response"] == "Server status"


def test_chat_api_non_command_input_asks_the_configured_agent(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "noncommanduser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    # ask_stream is patched with a plain async-generator function rather
    # than a MagicMock (a MagicMock's return_value isn't itself an async
    # generator, and chat_api's factory() does `async for event in
    # ai_agent_client.ask_stream(...)`) - so calls are captured manually
    # instead of via assert_called_once()/call_args.
    calls = []

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        calls.append(url)
        yield {"type": "final", "response": "hi back", "tools_used": [], "tool_calls": [],
               "provider_id": "openai", "model": "gpt-5.6-sol", "total_tokens": None, "cancelled": False}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": [], "provider": "claude-agent"})

    assert response.status_code == 200
    body = _read_sse_events(response)[-1]
    assert body["kind"] == "assistant"
    assert len(calls) == 1
    assert calls[0] == chat_index.agent_registry.get_agent("claude-agent")["url"]


def test_chat_api_auto_summarizes_before_send_when_threshold_crossed(tmp_path, monkeypatch):
    # Phase 5: the turn that PUSHES usage over threshold stores that
    # reading; the NEXT turn is the one that reads it back and triggers
    # the pre-send auto-summarize, before its own question ever reaches
    # ask(). This drives two real /chat/api/chat calls through the actual
    # chat_api route (and the real summarization.summarize_chat/
    # chats_store underneath), stubbing only the ai_agent_client network
    # boundary - same boundary this file's other chat_api tests already
    # stub.
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "autosumuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    turn1_result = {
        "response": "hello one back", "tools_used": [], "tool_calls": [], "provider_id": "openrouter",
        "model": "openrouter/free", "total_tokens": 95000, "context_tokens": 95000,
        "context_window": 100000, "cancelled": False,
    }
    turn2_result = {
        "response": "hello two back", "tools_used": [], "tool_calls": [], "provider_id": "openrouter",
        "model": "openrouter/free", "total_tokens": 500, "context_tokens": 500,
        "context_window": 100000, "cancelled": False,
    }
    interpret_result = {"response": "SUMMARY: verbatim path /a/b.txt preserved.", "model": "openrouter/free"}

    # ask_stream is patched with a plain async-generator function (see
    # test_chat_api_non_command_input_asks_the_configured_agent above for
    # why a MagicMock won't do) that hands back each queued result in
    # turn order and records the history it was called with.
    ask_results = [turn1_result, turn2_result]
    ask_calls = []

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        ask_calls.append(history)
        yield {"type": "final", **ask_results[len(ask_calls) - 1]}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream), \
         patch.object(chat_index.ai_agent_client, "interpret", return_value=interpret_result) as fake_interpret:
        r1 = client.post(
            "/chat/api/chat", json={"question": "hello one", "history": [], "provider": "claude-agent"}
        )
        assert r1.status_code == 200
        chat_id = _read_sse_events(r1)[-1]["chat_id"]

        chat_after_1 = client.get(f"/chat/api/chats/{chat_id}").get_json()
        history = [
            {"role": m["role"], "content": m["content"]}
            for m in chat_after_1["messages"] if m.get("kind") != "log_attachment"
        ]
        r2 = client.post(
            "/chat/api/chat",
            json={"question": "hello two", "history": history, "chat_id": chat_id, "provider": "claude-agent"},
        )
        assert r2.status_code == 200

    # interpret() (summarize_chat's mechanism) ran exactly once, between
    # the two ask_stream() calls - proof the auto-trigger fired for turn
    # 2, not turn 1 (nothing to summarize yet on turn 1).
    fake_interpret.assert_called_once()
    assert len(ask_calls) == 2
    # turn 2's ask_stream() must have been sent the REBUILT
    # (post-summarize) history - just the fresh summary message, never the
    # raw turn-1 exchange or a log_attachment.
    turn2_history_sent = ask_calls[1]
    assert turn2_history_sent == [{"role": "assistant", "content": interpret_result["response"]}]

    chat = client.get(f"/chat/api/chats/{chat_id}").get_json()
    kinds = [(m.get("role"), m.get("kind")) for m in chat["messages"]]
    assert chat["messages"][0]["kind"] == "summary", kinds
    assert chat["messages"][0]["content"] == interpret_result["response"]
    assert chat["messages"][1]["kind"] == "log_attachment", kinds
    assert "hello one" in chat["messages"][1]["content"], "log_attachment must contain the pre-summarize turn"
    assert "hello one back" in chat["messages"][1]["content"]
    assert chat["messages"][2]["role"] == "user" and chat["messages"][2]["content"] == "hello two", kinds
    assert chat["messages"][3]["role"] == "assistant" and chat["messages"][3]["content"] == "hello two back", kinds
    # The user's actual turn-2 question/answer must not have leaked into
    # the summary text, which was built from content available BEFORE
    # this question was asked.
    assert "hello two" not in chat["messages"][0]["content"]


def test_chat_api_auto_summarize_fires_again_on_a_second_threshold_crossing(tmp_path, monkeypatch):
    # Regression guard for the "not just once" requirement: a SECOND
    # crossing later in the same chat must trigger a second summarize
    # cycle, and the log attachment must stay cumulative (cover the
    # entire original history, not just the newest slice) across it.
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "autosumuser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    over_threshold = {"context_tokens": 96000, "context_window": 100000}
    under_threshold = {"context_tokens": 500, "context_window": 100000}

    def ask_result(response_text, usage):
        return {
            "response": response_text, "tools_used": [], "tool_calls": [], "provider_id": "openrouter",
            "model": "openrouter/free", "total_tokens": usage["context_tokens"], "cancelled": False, **usage,
        }

    ask_results = [
        ask_result("hello one back", over_threshold),    # turn 1: nothing to summarize yet
        ask_result("hello two back", under_threshold),   # turn 2: 1st auto-summarize fires before this call (based on turn 1's over-threshold reading)
        ask_result("hello three back", over_threshold),  # turn 3: below threshold coming in (turn 2's reading), no trigger
        ask_result("hello four back", under_threshold),  # turn 4: 2nd auto-summarize fires before this call (based on turn 3's over-threshold reading)
    ]
    interpret_results = [
        {"response": "SUMMARY v1", "model": "openrouter/free"},
        {"response": "SUMMARY v2", "model": "openrouter/free"},
    ]

    # See test_chat_api_non_command_input_asks_the_configured_agent for why
    # ask_stream is a plain async-generator function, not a MagicMock.
    ask_call_count = [0]

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        index = ask_call_count[0]
        ask_call_count[0] += 1
        yield {"type": "final", **ask_results[index]}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream), \
         patch.object(chat_index.ai_agent_client, "interpret", side_effect=interpret_results) as fake_interpret:
        chat_id = None
        for question in ["hello one", "hello two", "hello three", "hello four"]:
            history = []
            if chat_id is not None:
                chat_now = client.get(f"/chat/api/chats/{chat_id}").get_json()
                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in chat_now["messages"] if m.get("kind") != "log_attachment"
                ]
            payload = {"question": question, "history": history, "provider": "claude-agent"}
            if chat_id is not None:
                payload["chat_id"] = chat_id
            resp = client.post("/chat/api/chat", json=payload)
            assert resp.status_code == 200
            chat_id = _read_sse_events(resp)[-1]["chat_id"]

    assert ask_call_count[0] == 4
    assert fake_interpret.call_count == 2

    chat = client.get(f"/chat/api/chats/{chat_id}").get_json()
    kinds = [(m.get("role"), m.get("kind")) for m in chat["messages"]]
    summary_count = sum(1 for m in chat["messages"] if m.get("kind") == "summary")
    assert summary_count == 1, f"exactly one summary message at the head at all times, got {kinds}"
    assert chat["messages"][0]["content"] == "SUMMARY v2", "2nd cycle must replace, not append to, the summary"
    log_content = chat["messages"][1]["content"]
    assert "hello one" in log_content, f"cumulative log lost the original turn-1 content: {kinds}"
    assert "hello two" in log_content, f"cumulative log lost turn 2 (between the two cycles): {kinds}"
    assert "hello three" in log_content, f"cumulative log lost turn 3 (between the two cycles): {kinds}"


def test_chat_api_cancelled_result_shows_cancelled_message_without_error_logging(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "canceluser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        yield {"type": "final", "response": "⏹️ Cancelled.", "cancelled": True}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": [], "request_id": "req-1"})

    assert response.status_code == 200
    assert _read_sse_events(response)[-1]["response"] == "⏹️ Cancelled."
    with app.app_context():
        errors = db.session.query(LogEntry).filter_by(kind="error", account_id=account_id).all()
        assert errors == []


def test_cancel_chat_api_does_not_forward_an_unowned_request_id(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "cancelapiuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index.ai_agent_client, "cancel") as fake_cancel:
        response = client.post(
            "/chat/api/chat/cancel", json={"request_id": "req-1", "provider": "claude-agent"}
        )

    assert response.status_code == 204
    fake_cancel.assert_not_called()


def test_cancel_chat_api_is_a_noop_for_an_unknown_agent(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "cancelapiuser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index.ai_agent_client, "cancel") as fake_cancel:
        response = client.post(
            "/chat/api/chat/cancel", json={"request_id": "req-1", "provider": "no-such-agent"}
        )

    assert response.status_code == 204
    fake_cancel.assert_not_called()


def test_chat_attach_api_requires_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "noattachaccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/chat/api/chat/attach", data={"file": (io.BytesIO(b"hi"), "notes.txt")}, content_type="multipart/form-data"
    )

    assert response.status_code == 403


def test_chat_attach_api_extracts_text_from_a_plain_file(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "attachuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/chat/api/chat/attach",
        data={"file": (io.BytesIO(b"hello world"), "notes.txt")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body == {"filename": "notes.txt", "text": "hello world", "char_count": 11, "truncated": False}


def test_chat_attach_api_requires_a_file(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "attachuser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/chat/api/chat/attach", data={}, content_type="multipart/form-data")

    assert response.status_code == 400
    assert "required" in response.get_json()["error"]


def test_chat_attach_api_returns_400_for_unsupported_file_type(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "attachuser3", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post(
        "/chat/api/chat/attach",
        data={"file": (io.BytesIO(b"binarydata"), "archive.zip")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "Can't read" in response.get_json()["error"]


def test_providers_api_reports_live_status_per_configured_agent(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "providersapiuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    def _fake_status(url):
        if "9100" in url:
            return {"provider_id": "claude", "model": "claude-sonnet-5", "available": True, "reason": None, "cooldown_seconds_remaining": 0}
        raise ConnectionRefusedError("no one listening")

    with patch.object(chat_index.ai_agent_client, "status", side_effect=_fake_status):
        response = client.get("/chat/api/providers")

    assert response.status_code == 200
    entries = {entry["id"]: entry for entry in response.get_json()}
    assert entries["claude-agent"]["available"] is True
    assert entries["claude-agent"]["model"] == "claude-sonnet-5"
    assert entries["openai-agent"]["available"] is False
    assert entries["openai-agent"]["reason"] == "unreachable"


def test_providers_api_refresh_param_reloads_agent_registry(tmp_path, monkeypatch):
    """?refresh=1 (script.js's dropdown refresh button) must re-read
    config_agents.json before listing agents, so an ai_agent instance
    that registered/deregistered itself (see ai_agent/src/
    agent_registry.py) after this process's own import-time load shows up
    without a chat_app restart - see providers_api's docstring."""
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "providersrefreshuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index.agent_registry, "reload") as fake_reload, \
         patch.object(chat_index.ai_agent_client, "status", side_effect=ConnectionRefusedError("no one listening")):
        client.get("/chat/api/providers")
        fake_reload.assert_not_called()

        client.get("/chat/api/providers?refresh=1")
        fake_reload.assert_called_once()


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
                    ),
                    commands.CommandParam(
                        name="file_path",
                        required=True,
                        type="string",
                        has_default=False,
                        default=None,
                        format="file",
                    ),
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
                        "examples": [],
                        "format": None,
                        "input": None,
                        "options": None,
                        "options_url": None,
                        "enum": [],
                        "minimum": None,
                        "maximum": None,
                        "step": None,
                        "max_length": None,
                        "pattern": None,
                        "depends_on": None,
                        "sets": {},
                        "shows": {},
                        "initial": None,
                    },
                    {
                        "name": "file_path",
                        "required": True,
                        "type": "string",
                        "has_default": False,
                        "default": None,
                        "examples": [],
                        "format": "file",
                        "input": None,
                        "options": None,
                        "options_url": None,
                        "enum": [],
                        "minimum": None,
                        "maximum": None,
                        "step": None,
                        "max_length": None,
                        "pattern": None,
                        "depends_on": None,
                        "sets": {},
                        "shows": {},
                        "initial": None,
                    },
                ],
            }
        }
    }
    fake_build.assert_called_once_with(["reference", "other"])


def test_commands_api_requires_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nocommandsapiaccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/api/commands")

    assert response.status_code == 403


def test_summarize_chat_api_requires_chat_access_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nosummarizeaccess", [])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/chat/api/chats/some-id/summarize")

    assert response.status_code == 403


def test_summarize_chat_api_404s_for_an_unknown_chat(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "summarizeuser1", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.post("/chat/api/chats/does-not-exist/summarize")

    assert response.status_code == 404


def test_summarize_chat_api_502s_when_no_agent_is_configured(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "summarizeuser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    with app.app_context():
        chat_id = chat_index.chats_store.save_chat(
            chat_index.settings.chats_db_path, "summarizeuser2", None, [{"role": "user", "content": "hi"}]
        )

    with patch.object(chat_index.agent_registry, "resolve_agent", return_value=None):
        response = client.post(f"/chat/api/chats/{chat_id}/summarize")

    assert response.status_code == 502
    assert "No ai_agent is configured" in response.get_json()["error"]


def test_summarize_chat_api_returns_the_updated_chat_on_success(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "summarizeuser3", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    with app.app_context():
        chat_id = chat_index.chats_store.save_chat(
            chat_index.settings.chats_db_path, "summarizeuser3", None, [{"role": "user", "content": "hi"}]
        )

    with patch.object(chat_index.summarization, "summarize_chat", return_value=True) as fake_summarize:
        response = client.post(f"/chat/api/chats/{chat_id}/summarize", json={"provider": "claude-agent"})

    assert response.status_code == 200
    assert response.get_json()["id"] == chat_id
    fake_summarize.assert_called_once()
    assert fake_summarize.call_args.args[3] == chat_index.agent_registry.get_agent("claude-agent")["url"]


def test_summarize_chat_api_returns_400_when_nothing_new_to_summarize(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "summarizeuser4", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    with app.app_context():
        chat_id = chat_index.chats_store.save_chat(
            chat_index.settings.chats_db_path, "summarizeuser4", None, [{"role": "user", "content": "hi"}]
        )

    with patch.object(chat_index.summarization, "summarize_chat", return_value=False):
        response = client.post(f"/chat/api/chats/{chat_id}/summarize")

    assert response.status_code == 400


def test_summarize_chat_api_502s_and_leaves_chat_untouched_on_summarize_error(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "summarizeuser5", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    with app.app_context():
        chat_id = chat_index.chats_store.save_chat(
            chat_index.settings.chats_db_path, "summarizeuser5", None, [{"role": "user", "content": "hi"}]
        )

    error = chat_index.summarization.SummarizeError("Could not reach the AI agent: boom")
    with patch.object(chat_index.summarization, "summarize_chat", side_effect=error):
        response = client.post(f"/chat/api/chats/{chat_id}/summarize")

    assert response.status_code == 502
    assert response.get_json()["error"] == "Could not reach the AI agent: boom"
    with app.app_context():
        chat = chat_index.chats_store.get_chat(chat_index.settings.chats_db_path, "summarizeuser5", chat_id)
        assert chat["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_api_llm_history_excludes_log_attachment_messages(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "loghistoryuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    history = [
        {"role": "assistant", "kind": "summary", "content": "prior context, summarized"},
        {"role": "assistant", "kind": "log_attachment", "content": "the entire raw original transcript"},
    ]
    calls = []

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        calls.append(history)
        yield {"type": "final", "response": "hi back", "tools_used": [], "tool_calls": [],
               "provider_id": "openai", "model": "gpt-5.6-sol", "total_tokens": None, "cancelled": False}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream):
        response = client.post("/chat/api/chat", json={"question": "hi", "history": history})

    assert response.status_code == 200
    sent_history = calls[0]
    assert sent_history == [{"role": "assistant", "content": "prior context, summarized"}]


def test_chat_page_has_no_inline_event_handlers(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "cspuser2", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    response = client.get("/chat/")

    assert response.status_code == 200
    assert b"onclick=" not in response.data


def test_background_chat_is_owned_and_survives_disconnect(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    alice = _create_account(app, "alice", ["chat.access"])
    bob = _create_account(app, "bob", ["chat.access"])
    client, other = app.test_client(), app.test_client()
    _login_as(client, alice)
    _login_as(other, bob)
    release = threading.Event()

    async def delayed_stream(*args, **kwargs):
        yield {"type": "token", "text": "Working"}
        assert release.wait(5), "test must release the background worker"
        yield {"type": "final", "response": "Finished"}

    with patch.object(chat_index.ai_agent_client, "ask_stream", delayed_stream):
        response = client.post("/chat/api/chat", json={"question": "hello"}, buffered=False)
        try:
            chat_id = response.headers.get("X-Chat-Id")
            assert chat_id
            response.close()
            chats = client.get("/chat/api/chats").get_json()
            assert chats[0]["activity"]["status"] == "running"
            active_chat = client.get(f"/chat/api/chats/{chat_id}").get_json()
            assert active_chat["pending_question"] == "hello"
            assert active_chat["activity"]["status"] == "running"
            assert other.get(f"/chat/api/chats/{chat_id}").status_code == 404
            assert other.get("/chat/api/chats").get_json() == []
            assert other.get(f"/chat/api/chats/{chat_id}/events").status_code == 404
            assert other.post(f"/chat/api/chats/{chat_id}/cancel").status_code == 404
            assert client.post("/chat/api/chat", json={"question": "again", "chat_id": chat_id}).status_code == 409
        finally:
            release.set()
        events = _read_sse_events(client.get(f"/chat/api/chats/{chat_id}/events"))
        assert [event["type"] for event in events] == ["token", "final"]
        assert [event["sequence"] for event in events] == [1, 2]
        assert events[-1]["response"] == "Finished"
        replay = _read_sse_events(client.get(f"/chat/api/chats/{chat_id}/events?after_sequence=1"))
        assert len(replay) == 1
        assert replay[0]["type"] == "final"
        chat = client.get(f"/chat/api/chats/{chat_id}").get_json()
        assert [message["content"] for message in chat["messages"]] == ["hello", "Finished"]
        assert chat["last_response_at"]
        assert chat["pending_question"] is None
        listed = client.get("/chat/api/chats").get_json()[0]
        assert listed["last_response_at"]
        assert listed["activity"]["status"] == "completed"


def test_deleting_running_chat_cancels_before_delete_without_recreating_chat(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "deleteworker", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    release = threading.Event()
    cancelled_while_present = []

    async def delayed_stream(*args, **kwargs):
        yield {"type": "token", "text": "Working"}
        assert release.wait(5)
        yield {"type": "final", "response": "Cancelled", "cancelled": True}

    def cancel_agent(url, request_id):
        cancelled_while_present.append(
            chat_index.chats_store.get_chat(chat_index.settings.chats_db_path, "deleteworker", chat_id) is not None
        )

    with patch.object(chat_index.ai_agent_client, "ask_stream", delayed_stream), \
         patch.object(chat_index.ai_agent_client, "cancel", cancel_agent):
        response = client.post("/chat/api/chat", json={"question": "hello", "request_id": "delete-turn"}, buffered=False)
        try:
            chat_id = response.headers.get("X-Chat-Id")
            assert chat_id
            response.close()
            registry = app.extensions["chat_jobs"]
            job = registry.get("deleteworker", chat_id)
            assert client.delete(f"/chat/api/chats/{chat_id}").status_code == 204
            assert cancelled_while_present == [True]
            assert registry.get("deleteworker", chat_id) is None
            assert not job.events
            assert job.history == []
            assert job.question == ""
        finally:
            release.set()
        job.thread.join(timeout=5)
        assert not job.thread.is_alive()
        assert client.get("/chat/api/chats").get_json() == []
        assert not job.events


def test_job_registry_bounds_replay_and_rejects_other_owners(tmp_path):
    registry = chat_index.ChatJobRegistry(tmp_path / "jobs.db", event_buffer_size=3)
    chat_id = chat_index.chats_store.save_chat(registry.db_path, "alice", None, [])

    def run_turn(job):
        for number in range(8):
            yield {"type": "token", "text": str(number)}
        yield {"type": "final", "response": "done"}

    job = registry.start("alice", chat_id, None, "bounded", "hi", [], run_turn=run_turn)
    job.thread.join(timeout=5)
    assert not job.thread.is_alive()
    events = list(registry.subscribe("alice", chat_id, 0))
    assert [event["sequence"] for event in events] == [7, 8, 9]
    assert events[-1]["response"] == "done"
    assert list(registry.subscribe("alice", chat_id, 9)) == []
    assert registry.get("bob", chat_id) is None
    assert registry.status_for_user("bob") == {}
    assert not registry.cancel("bob", chat_id)
    with pytest.raises(chat_index.chats_store.UnknownChat):
        registry.subscribe("bob", chat_id, 0)
    with pytest.raises(chat_index.chats_store.UnknownChat):
        registry.start("bob", chat_id, None, "bad", "hi", [], run_turn=run_turn)

    next_job = registry.start("alice", chat_id, None, "next", "hi", [], run_turn=run_turn)
    next_job.thread.join(timeout=5)
    assert [event["sequence"] for event in registry.subscribe("alice", chat_id, 9)] == [16, 17, 18]


def test_job_finishing_normally_after_cancel_request_is_completed(tmp_path):
    """Cancellation is cooperative: the terminal provider outcome wins."""
    registry = chat_index.ChatJobRegistry(tmp_path / "jobs.db")
    chat_id = chat_index.chats_store.save_chat(registry.db_path, "alice", None, [])
    started, release = threading.Event(), threading.Event()

    def run_turn(job):
        started.set()
        yield {"type": "token", "text": "Working"}
        assert release.wait(5)
        yield {"type": "final", "response": "Completed normally"}

    job = registry.start("alice", chat_id, None, "cancel-requested", "hi", [], run_turn=run_turn)
    assert started.wait(5)
    assert registry.cancel("alice", chat_id)
    release.set()
    job.thread.join(timeout=5)

    assert not job.thread.is_alive()
    assert registry.status_for_user("alice")[chat_id]["status"] == "completed"
    assert list(registry.subscribe("alice", chat_id))[-1]["response"] == "Completed normally"


def test_background_cancel_uses_owned_provider_and_request_and_persists_once(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "stopworker", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)
    started, release = threading.Event(), threading.Event()
    cancellations = []
    provider_requests = []

    async def delayed_stream(url, question, history, extensions, request_id, **kwargs):
        provider_requests.append(request_id)
        started.set()
        assert release.wait(5)
        yield {"type": "final", "response": "Stopped", "cancelled": True}
        yield {"type": "final", "response": "must not be persisted twice"}

    def cancel_agent(url, request_id):
        cancellations.append((url, request_id))
        release.set()

    with patch.object(chat_index.ai_agent_client, "ask_stream", delayed_stream), \
         patch.object(chat_index.ai_agent_client, "cancel", cancel_agent):
        response = client.post("/chat/api/chat", json={
            "question": "hello", "provider": "claude-agent", "request_id": "stop-turn", "background": True,
        })
        try:
            assert response.status_code == 202
            chat_id = response.get_json()["chat_id"]
            assert started.wait(5)
            assert client.post(f"/chat/api/chats/{chat_id}/cancel").status_code == 204
            events = _read_sse_events(client.get(f"/chat/api/chats/{chat_id}/events"))
        finally:
            release.set()
        assert provider_requests[0] != "stop-turn"
        assert cancellations == [("http://127.0.0.1:9100/mcp", provider_requests[0])]
        assert len(events) == 1
        assert events[0]["cancelled"]
        assert app.extensions["chat_jobs"].status_for_user("stopworker")[chat_id]["status"] == "cancelled"
        assert len(client.get(f"/chat/api/chats/{chat_id}").get_json()["messages"]) == 2
        assert client.get(f"/chat/api/chats/{chat_id}").get_json()["last_response_at"] is None
        assert len(_read_sse_events(client.get(f"/chat/api/chats/{chat_id}/events"))) == 1
        with app.app_context():
            assert db.session.query(LogEntry).filter_by(kind="chat_trace", account_id=account_id).count() == 1


@pytest.mark.parametrize("outcome", ["cancelled", "failed", "command", "usage_blocked", "completed"])
@pytest.mark.parametrize("previous_response", [None, "2026-09-01T12:00:00+00:00"])
def test_only_completed_turns_advance_response_timestamp(tmp_path, monkeypatch, outcome, previous_response):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    client = app.test_client()
    _login_as(client, _create_account(app, "timestamp", ["chat.access"]))
    chat_id = chat_index.chats_store.save_chat(chat_index.settings.chats_db_path, "timestamp", None, [])
    if previous_response:
        chat_index.chats_store.record_last_response(chat_index.settings.chats_db_path, "timestamp", chat_id, previous_response)

    async def stream(*args, **kwargs):
        yield {"type": "final", "response": "result", "cancelled": outcome == "cancelled", "failed": outcome == "failed"}

    with patch.object(chat_index.ai_agent_client, "ask_stream", stream), \
         patch.object(chat_index.commands, "execute_command", return_value="command result"), \
         patch.object(chat_index.usage_limits, "check_limit", return_value=(outcome != "usage_blocked", "Limit reached", None)):
        events = _read_sse_events(client.post("/chat/api/chat", json={
            "question": "/help" if outcome == "command" else "question", "chat_id": chat_id,
        }))
    assert events[-1]["type"] == "final"
    stored = client.get(f"/chat/api/chats/{chat_id}").get_json()
    assert len(stored["messages"]) == 2
    if outcome in ("completed", "command"):
        assert stored["last_response_at"]
        assert stored["last_response_at"] != previous_response
    else:
        assert stored["last_response_at"] == previous_response


@pytest.mark.parametrize(
    ("question", "terminal_event", "response_text"),
    [
        ("next question", {"type": "final", "response": "Stopped", "cancelled": True}, "Stopped"),
        ("next question", {"type": "final", "response": "Failed", "failed": True}, "Failed"),
        ("/help", None, "Command result"),
    ],
)
def test_chat_detail_snapshots_running_job_before_terminal_transcript(
    tmp_path, monkeypatch, question, terminal_event, response_text,
):
    """A terminal turn between the two detail reads must still be replayable.

    Failed and cancelled turns deliberately retain the prior
    ``last_response_at`` value, so the browser cannot infer this completion
    from that timestamp.  Force the worker to finish after its running-job
    snapshot but before the transcript lookup and require the detail response
    to retain that running snapshot alongside the current transcript.
    """
    app = _build_chat_test_app(tmp_path, monkeypatch)
    client = app.test_client()
    _login_as(client, _create_account(app, "detailrace", ["chat.access"]))
    previous_response = "2026-09-01T12:00:00+00:00"
    chat_id = chat_index.chats_store.save_chat(
        chat_index.settings.chats_db_path, "detailrace", None,
        [{"role": "user", "content": "Earlier"}, {"role": "assistant", "content": "Earlier reply"}],
    )
    chat_index.chats_store.record_last_response(
        chat_index.settings.chats_db_path, "detailrace", chat_id, previous_response,
    )
    started, release = threading.Event(), threading.Event()

    async def delayed_stream(*args, **kwargs):
        started.set()
        assert release.wait(5)
        yield terminal_event

    def delayed_command(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return response_text

    with patch.object(chat_index.ai_agent_client, "ask_stream", delayed_stream), \
         patch.object(chat_index.commands, "execute_command", delayed_command):
        response = client.post("/chat/api/chat", json={
            "question": question, "chat_id": chat_id, "background": True,
        })
        assert response.status_code == 202
        assert started.wait(5)
        job = app.extensions["chat_jobs"].get("detailrace", chat_id)

        class FinishAfterJobSnapshot:
            """Complete the turn once the route releases its job snapshot."""

            def __init__(self, condition):
                self.condition = condition

            def __enter__(self):
                return self.condition.__enter__()

            def __exit__(self, *args):
                result = self.condition.__exit__(*args)
                if threading.current_thread() is threading.main_thread():
                    release.set()
                    job.thread.join(timeout=5)
                    assert not job.thread.is_alive()
                return result

            def __getattr__(self, name):
                return getattr(self.condition, name)

        job.condition = FinishAfterJobSnapshot(job.condition)
        detail = client.get(f"/chat/api/chats/{chat_id}").get_json()

    assert [message["content"] for message in detail["messages"]] == [
        "Earlier", "Earlier reply", question, response_text,
    ]
    if terminal_event is None and question.startswith("/"):
        assert detail["last_response_at"] != previous_response
    else:
        assert detail["last_response_at"] == previous_response
    assert detail["activity"]["status"] == "running"
    assert detail["pending_question"] == question
    assert detail["messages"][-1]["request_id"] == detail["activity"]["request_id"]


def test_background_endpoints_require_chat_permission(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "nojobaccess", [])
    client = app.test_client()
    _login_as(client, account_id)
    assert client.get("/chat/api/chats/unknown/events").status_code == 403
    assert client.post("/chat/api/chats/unknown/cancel").status_code == 403


def test_cancel_during_startup_prevents_provider_call(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    client = app.test_client()
    _login_as(client, _create_account(app, "earlystop", ["chat.access"]))
    startup, release = threading.Event(), threading.Event()
    provider_calls = []

    def blocked_startup(*args):
        startup.set()
        assert release.wait(5)

    async def provider(*args, **kwargs):
        provider_calls.append(args)
        yield {"type": "final", "response": "Should not run"}

    with patch.object(chat_index, "_maybe_auto_summarize", blocked_startup), \
         patch.object(chat_index.ai_agent_client, "ask_stream", provider), \
         patch.object(chat_index.ai_agent_client, "cancel") as provider_cancel:
        response = client.post("/chat/api/chat", json={"question": "hello", "background": True})
        chat_id = response.get_json()["chat_id"]
        try:
            assert startup.wait(5)
            assert client.post(f"/chat/api/chats/{chat_id}/cancel").status_code == 204
        finally:
            release.set()
        events = _read_sse_events(client.get(f"/chat/api/chats/{chat_id}/events"))
        assert provider_calls == []
        provider_cancel.assert_not_called()
        assert events[-1]["cancelled"]
        assert len(client.get(f"/chat/api/chats/{chat_id}").get_json()["messages"]) == 2


def test_same_client_request_id_cannot_cross_cancel_users(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    clients = {name: app.test_client() for name in ("alice", "bob")}
    for name, client in clients.items():
        _login_as(client, _create_account(app, name, ["chat.access"]))
    started = {name: threading.Event() for name in clients}
    release = threading.Event()
    provider_ids, cancelled_ids = {}, set()

    async def provider(url, question, history, extensions, request_id, **kwargs):
        provider_ids[question] = request_id
        started[question].set()
        assert release.wait(5)
        cancelled = request_id in cancelled_ids
        yield {"type": "final", "response": "Stopped" if cancelled else "Finished", "cancelled": cancelled}

    def cancel_provider(url, request_id):
        cancelled_ids.add(request_id)

    with patch.object(chat_index.ai_agent_client, "ask_stream", provider), \
         patch.object(chat_index.ai_agent_client, "cancel", cancel_provider):
        chat_ids = {}
        try:
            for name, client in clients.items():
                response = client.post("/chat/api/chat", json={
                    "question": name, "request_id": "same-client-id", "background": True,
                    "provider": "claude-agent",
                })
                chat_ids[name] = response.get_json()["chat_id"]
                assert started[name].wait(5)
            assert clients["alice"].post("/chat/api/chat/cancel", json={
                "request_id": "same-client-id", "provider": "claude-agent",
            }).status_code == 204
        finally:
            release.set()
        results = {name: _read_sse_events(client.get(f"/chat/api/chats/{chat_ids[name]}/events"))[-1]
                   for name, client in clients.items()}
        assert results["alice"]["cancelled"]
        assert not results["bob"]["cancelled"]
        assert provider_ids["alice"] != provider_ids["bob"]
        assert "same-client-id" not in provider_ids.values()


def test_completed_job_replay_expires_and_releases_transcript(tmp_path, monkeypatch):
    from src.services import chat_jobs

    timers = []

    class ManualTimer:
        def __init__(self, interval, callback, args=()):
            self.callback, self.args = callback, args
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            pass

    monkeypatch.setattr(chat_jobs, "Timer", ManualTimer, raising=False)
    registry = chat_index.ChatJobRegistry(tmp_path / "jobs.db")
    chat_id = chat_index.chats_store.save_chat(registry.db_path, "alice", None, [])

    def run_turn(*args):
        yield {"type": "final", "response": "Retained for reconnect"}

    job = registry.start("alice", chat_id, None, "replay", "private question",
                         [{"role": "user", "content": "private history"}], run_turn=run_turn)
    job.thread.join(timeout=5)
    assert list(registry.subscribe("alice", chat_id))[-1]["response"] == "Retained for reconnect"
    assert job.history == []
    assert job.question == ""
    assert len(timers) == 1
    timers[0].callback(*timers[0].args)
    assert registry.get("alice", chat_id) is None
    assert not job.events
    with pytest.raises(chat_index.chats_store.UnknownChat):
        registry.subscribe("alice", chat_id)


def test_completed_job_retention_is_capped_without_evicting_running_jobs(tmp_path):
    registry = chat_index.ChatJobRegistry(tmp_path / "jobs.db", max_completed_jobs=2)
    release = threading.Event()
    running_id = chat_index.chats_store.save_chat(registry.db_path, "alice", None, [])

    def blocked_turn(*args):
        assert release.wait(5)
        yield {"type": "final", "response": "done"}

    running = registry.start("alice", running_id, None, None, "hi", [], run_turn=blocked_turn)
    completed = []
    try:
        for number in range(3):
            chat_id = chat_index.chats_store.save_chat(registry.db_path, "alice", None, [])
            job = registry.start("alice", chat_id, None, None, "hi", [],
                                 run_turn=lambda *args: iter([{"type": "final", "response": "done"}]))
            job.thread.join(timeout=5)
            completed.append(job)
        assert registry.get("alice", running_id) is running
        assert registry.get("alice", completed[0].chat_id) is None
        assert not completed[0].events
        assert len(registry.status_for_user("alice")) == 3
        cursor = completed[0].sequence
        replacement = registry.start("alice", completed[0].chat_id, None, None, "again", [],
                                     run_turn=lambda *args: iter([{"type": "final", "response": "again"}]))
        replacement.thread.join(timeout=5)
        assert list(registry.subscribe("alice", replacement.chat_id, cursor))[-1]["response"] == "again"
    finally:
        release.set()
        running.thread.join(timeout=5)


def test_replay_expiring_during_subscription_returns_not_found(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    client = app.test_client()
    _login_as(client, _create_account(app, "expiredreplay", ["chat.access"]))

    async def provider(*args, **kwargs):
        yield {"type": "final", "response": "done"}

    with patch.object(chat_index.ai_agent_client, "ask_stream", provider):
        response = client.post("/chat/api/chat", json={"question": "hello"})
        chat_id = _read_sse_events(response)[-1]["chat_id"]
    registry = app.extensions["chat_jobs"]
    job = registry.get("expiredreplay", chat_id)
    subscribe = registry.subscribe

    def subscribe_after_expiry(*args):
        registry._expire(job)
        return subscribe(*args)

    monkeypatch.setattr(registry, "subscribe", subscribe_after_expiry)
    assert client.get(f"/chat/api/chats/{chat_id}/events").status_code == 404
    assert client.get(f"/chat/api/chats/{chat_id}").get_json()["messages"][-1]["content"] == "done"


def test_replay_expiring_before_lazy_subscription_consumption_returns_sse_error(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    client = app.test_client()
    _login_as(client, _create_account(app, "lazyexpiry", ["chat.access"]))

    async def provider(*args, **kwargs):
        yield {"type": "final", "response": "done"}

    with patch.object(chat_index.ai_agent_client, "ask_stream", provider):
        response = client.post("/chat/api/chat", json={"question": "hello"})
        chat_id = _read_sse_events(response)[-1]["chat_id"]
    registry = app.extensions["chat_jobs"]
    job = registry.get("lazyexpiry", chat_id)
    subscribe = registry.subscribe

    def subscribe_then_expire(*args):
        events = subscribe(*args)
        registry._expire(job)
        return events

    monkeypatch.setattr(registry, "subscribe", subscribe_then_expire)
    events = _read_sse_events(client.get(f"/chat/api/chats/{chat_id}/events"))
    assert events == [{
        "type": "error",
        "message": "Chat replay expired. Reload the saved chat.",
        "failed": True,
    }]
    assert client.get(f"/chat/api/chats/{chat_id}").get_json()["messages"][-1]["content"] == "done"


@pytest.mark.parametrize("question", ["hello", "/otp get_otp"])
def test_background_interrupted_turn_is_persisted_as_failure(tmp_path, monkeypatch, question):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "emptyworker", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def empty_stream(*args, **kwargs):
        if False:
            yield

    with patch.object(chat_index.ai_agent_client, "ask_stream", empty_stream), \
         patch.object(chat_index.commands, "execute_command", side_effect=RuntimeError("command failed")):
        response = client.post("/chat/api/chat", json={"question": question})
        events = _read_sse_events(response)
    chat_id = response.headers["X-Chat-Id"]
    assert events[-1]["type"] == "final"
    assert events[-1]["failed"]
    assert app.extensions["chat_jobs"].status_for_user("emptyworker")[chat_id]["status"] == "failed"
    assert len(client.get(f"/chat/api/chats/{chat_id}").get_json()["messages"]) == 2
    assert client.get(f"/chat/api/chats/{chat_id}/events?after_sequence=nope").status_code == 400
    assert client.get(f"/chat/api/chats/{chat_id}/events?after_sequence=-1").status_code == 400


def test_capability_labels_api_returns_labels_from_mcp_server(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "labelsapiuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    labels = {"sys": "Server Manager", "reports": "Reports"}
    with patch.object(chat_index, "fetch_capabilities", return_value=[{"name": "sys"}]), \
            patch.object(chat_index.tool_capabilities, "refresh_from") as refresh, \
            patch.object(chat_index.tool_capabilities, "known_labels", return_value=labels):
        response = client.get("/chat/api/capability-labels")

    assert response.status_code == 200
    assert response.get_json() == labels
    refresh.assert_called_once_with([{"name": "sys"}])


def test_capability_labels_api_falls_back_to_cached_labels_when_mcp_server_is_down(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "labelsdownuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index, "fetch_capabilities", side_effect=OSError("down")), \
            patch.object(chat_index.tool_capabilities, "refresh_from") as refresh, \
            patch.object(chat_index.tool_capabilities, "known_labels", return_value={"sys": "Server Manager"}):
        response = client.get("/chat/api/capability-labels")

    assert response.status_code == 200
    assert response.get_json() == {"sys": "Server Manager"}
    refresh.assert_not_called()


def test_commands_api_resolves_a_params_options_url_into_options(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "optionsurluser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    fake_registry = {
        "sys": {
            "check": commands.RegisteredCommand(
                capability="sys",
                name="check",
                description="check a system",
                tool_name="tool_server_check",
                params=[
                    commands.CommandParam(
                        name="capability", required=False, type="string", has_default=True, default="",
                        input="select", options_url="/system/check-capabilities",
                    )
                ],
            )
        }
    }
    options = [{"value": "server", "label": "Server Manager"}]
    with patch.object(chat_index.commands, "build_command_registry", return_value=fake_registry), \
            patch.object(chat_index, "fetch_options", return_value=options) as fetch:
        response = client.get("/chat/api/commands")

    param = response.get_json()["sys"]["check"]["params"][0]
    assert param["input"] == "select"
    assert param["options"] == options
    fetch.assert_called_once_with("/system/check-capabilities")


def test_commands_api_leaves_options_empty_when_the_options_fetch_fails(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "optionsfailuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    fake_registry = {
        "sys": {
            "check": commands.RegisteredCommand(
                capability="sys", name="check", description="d", tool_name="t",
                params=[commands.CommandParam(name="capability", required=False, type="string", options_url="/x")],
            )
        }
    }
    with patch.object(chat_index.commands, "build_command_registry", return_value=fake_registry), \
            patch.object(chat_index, "fetch_options", side_effect=OSError("down")):
        response = client.get("/chat/api/commands")

    assert response.status_code == 200
    assert response.get_json()["sys"]["check"]["params"][0]["options"] is None



def _dep_registry():
    return {
        "server": {
            "download_analysis": commands.RegisteredCommand(
                capability="server", name="download_analysis", description="d", tool_name="t",
                params=[
                    commands.CommandParam(
                        name="job_name", required=True, type="string", input="select",
                        options_url="/server/jobs/options?system_name={system_name}",
                        depends_on="system_name", sets={"job_count": "job_count"},
                    )
                ],
            )
        }
    }


def test_commands_api_does_not_prefetch_a_placeholder_options_url(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "placeholderoptsuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index.commands, "build_command_registry", return_value=_dep_registry()),             patch.object(chat_index, "fetch_options") as fetch:
        response = client.get("/chat/api/commands")

    param = response.get_json()["server"]["download_analysis"]["params"][0]
    assert param["options"] is None
    assert param["depends_on"] == "system_name"
    assert param["sets"] == {"job_count": "job_count"}
    fetch.assert_not_called()


def test_param_options_api_fills_the_placeholder_and_returns_the_options(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "paramoptsuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    options = [{"value": "JOB1", "label": "(0001) JOB1", "job_count": "0001"}]
    with patch.object(chat_index.commands, "build_command_registry", return_value=_dep_registry()),             patch.object(chat_index, "fetch_options", return_value=options) as fetch:
        response = client.get(
            "/chat/api/param-options?template=/server/jobs/options%3Fsystem_name%3D%7Bsystem_name%7D&arg.system_name=s4e demo"
        )

    assert response.status_code == 200
    assert response.get_json() == options
    fetch.assert_called_once_with("/server/jobs/options?system_name=s4e%20demo")


def test_param_options_api_rejects_a_template_no_command_declares(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "paramoptsbaduser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index.commands, "build_command_registry", return_value=_dep_registry()),             patch.object(chat_index, "fetch_options") as fetch:
        response = client.get("/chat/api/param-options?template=/nonexistent")

    assert response.status_code == 400
    fetch.assert_not_called()


def test_param_options_api_requires_the_placeholder_argument(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "paramoptsnoargsuser", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    with patch.object(chat_index.commands, "build_command_registry", return_value=_dep_registry()),             patch.object(chat_index, "fetch_options") as fetch:
        response = client.get("/chat/api/param-options?template=/server/jobs/options%3Fsystem_name%3D%7Bsystem_name%7D")

    assert response.status_code == 400
    fetch.assert_not_called()


def test_chat_api_counts_delegated_agents_toward_the_usage_limit(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    account_id = _create_account(app, "delegator", ["chat.access"])
    client = app.test_client()
    _login_as(client, account_id)

    async def fake_ask_stream(url, question, history, enabled_extensions, request_id=None, caveman=False):
        yield {"type": "final", "response": "ok", "tools_used": [], "tool_calls": [],
               "provider_id": "openai", "model": "gpt", "total_tokens": 40, "cancelled": False,
               "agent_usage": [
                   {"provider_id": "openai", "model": "gpt", "total_tokens": 40},
                   {"provider_id": "anthropic", "model": "claude", "total_tokens": 25},
               ]}

    with patch.object(chat_index.ai_agent_client, "ask_stream", fake_ask_stream), \
         patch.object(chat_index.usage_limits, "record_usage") as record_usage:
        client.post("/chat/api/chat", json={"question": "hi", "history": []})

    assert sum(c.args[2] for c in record_usage.call_args_list) == 65
