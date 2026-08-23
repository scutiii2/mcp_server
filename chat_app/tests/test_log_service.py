from src.models import Account, db
from src.services import log_service


def _make_account(username):
    account = Account(username=username, email=f"{username}@example.com", password_hash="hashed")
    db.session.add(account)
    db.session.commit()
    return account


def test_log_action_writes_entry_for_account(app):
    with app.app_context():
        account = _make_account("svc_action_user")

        entry = log_service.log_action(db.session, account, "test.source", "did a thing")

        assert entry.id is not None
        assert entry.kind == "action"
        assert entry.account_id == account.id
        assert entry.source == "test.source"
        assert entry.message == "did a thing"
        assert entry.details is None


def test_log_error_writes_entry_for_server_when_account_is_none(app):
    with app.app_context():
        entry = log_service.log_error(db.session, None, "test.source", "boom", details="trace")

        assert entry.kind == "error"
        assert entry.account_id is None
        assert entry.details == "trace"


def test_log_error_writes_entry_for_account(app):
    with app.app_context():
        account = _make_account("svc_error_user")

        entry = log_service.log_error(db.session, account, "test.source", "boom")

        assert entry.account_id == account.id


def test_list_entries_filters_by_kind_and_server_vs_account(app):
    with app.app_context():
        account = _make_account("svc_filter_user")
        log_service.log_action(db.session, account, "a", "account action")
        log_service.log_error(db.session, None, "b", "server error")
        log_service.log_error(db.session, account, "c", "account error")

        server_errors = log_service.list_entries(db.session, "error", account_id=None)
        account_errors = log_service.list_entries(db.session, "error", account_id=account.id)
        actions = log_service.list_entries(db.session, "action", account_id=account.id)

        assert [e.message for e in server_errors] == ["server error"]
        assert [e.message for e in account_errors] == ["account error"]
        assert [e.message for e in actions] == ["account action"]


def test_list_entries_respects_limit_and_orders_newest_first(app):
    with app.app_context():
        account = _make_account("svc_limit_user")
        for i in range(5):
            log_service.log_action(db.session, account, "a", f"action {i}")

        entries = log_service.list_entries(db.session, "action", account_id=account.id, limit=2)

        assert [e.message for e in entries] == ["action 4", "action 3"]


def test_log_chat_trace_writes_entry_for_account(app):
    with app.app_context():
        account = _make_account("svc_trace_user")

        entry = log_service.log_chat_trace(db.session, account, "chat.turn", "did a turn", details='{"tool_calls": []}')

        assert entry.id is not None
        assert entry.kind == "chat_trace"
        assert entry.account_id == account.id
        assert entry.source == "chat.turn"
        assert entry.message == "did a turn"
        assert entry.details == '{"tool_calls": []}'


def test_list_entries_filters_chat_trace_kind(app):
    with app.app_context():
        account = _make_account("svc_trace_filter_user")
        log_service.log_chat_trace(db.session, account, "chat.turn", "turn one")
        log_service.log_action(db.session, account, "a", "an action")

        traces = log_service.list_entries(db.session, "chat_trace", account_id=account.id)

        assert [e.message for e in traces] == ["turn one"]
