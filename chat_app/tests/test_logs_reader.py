from __future__ import annotations

import json

from chat_app.services import logs_reader


def _write_chat_log(log_dir, username, chat_id, lines):
    chat_dir = log_dir / "chats" / username
    chat_dir.mkdir(parents=True, exist_ok=True)
    (chat_dir / f"{chat_id}.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )


def _write_error_log(log_dir, reference, content):
    errors_dir = log_dir / "errors"
    errors_dir.mkdir(parents=True, exist_ok=True)
    (errors_dir / f"{reference}.log").write_text(content, encoding="utf-8")


# --- chat logs -------------------------------------------------------------


def test_list_chat_log_users_empty_when_nothing_logged_yet(tmp_path):
    assert logs_reader.list_chat_log_users(tmp_path) == []


def test_list_chat_log_users_lists_usernames(tmp_path):
    _write_chat_log(tmp_path, "alice", "chat1", [{"question": "hi"}])
    _write_chat_log(tmp_path, "bob", "chat2", [{"question": "hi"}])

    assert logs_reader.list_chat_log_users(tmp_path) == ["alice", "bob"]


def test_list_user_chat_logs_returns_empty_for_unknown_user(tmp_path):
    assert logs_reader.list_user_chat_logs(tmp_path, "nobody") == []


def test_list_user_chat_logs_rejects_a_path_traversal_username(tmp_path):
    """A username here comes straight from the URL - see logs_reader.py's
    module docstring for why this is validated the same strict way
    session_log.py's writer already sanitizes on the way in."""
    assert logs_reader.list_user_chat_logs(tmp_path, "../../etc") == []


def test_list_user_chat_logs_reports_id_and_size(tmp_path):
    _write_chat_log(tmp_path, "alice", "chat1", [{"question": "hi"}])

    [entry] = logs_reader.list_user_chat_logs(tmp_path, "alice")

    assert entry["chat_id"] == "chat1"
    assert entry["size"] > 0
    assert "updated_at" in entry


def test_read_chat_log_returns_none_for_unknown_chat(tmp_path):
    assert logs_reader.read_chat_log(tmp_path, "alice", "no-such-chat") is None


def test_read_chat_log_rejects_unsafe_chat_id(tmp_path):
    _write_chat_log(tmp_path, "alice", "chat1", [{"question": "hi"}])

    assert logs_reader.read_chat_log(tmp_path, "alice", "../chat1") is None


def test_read_chat_log_parses_every_line(tmp_path):
    _write_chat_log(
        tmp_path,
        "alice",
        "chat1",
        [{"question": "first"}, {"question": "second"}],
    )

    turns = logs_reader.read_chat_log(tmp_path, "alice", "chat1")

    assert [t["question"] for t in turns] == ["first", "second"]


def test_read_chat_log_skips_a_malformed_line_instead_of_failing(tmp_path):
    chat_dir = tmp_path / "chats" / "alice"
    chat_dir.mkdir(parents=True)
    (chat_dir / "chat1.jsonl").write_text(
        json.dumps({"question": "good"}) + "\nnot valid json\n", encoding="utf-8"
    )

    turns = logs_reader.read_chat_log(tmp_path, "alice", "chat1")

    assert [t["question"] for t in turns] == ["good"]


# --- error logs --------------------------------------------------------


def test_list_error_logs_empty_when_nothing_logged_yet(tmp_path):
    assert logs_reader.list_error_logs(tmp_path) == []


def test_list_error_logs_reports_reference_and_size(tmp_path):
    _write_error_log(tmp_path, "abc123", "traceback text")

    [entry] = logs_reader.list_error_logs(tmp_path)

    assert entry["reference"] == "abc123"
    assert entry["size"] > 0


def test_read_error_log_returns_none_for_unknown_reference(tmp_path):
    assert logs_reader.read_error_log(tmp_path, "no-such-ref") is None


def test_read_error_log_rejects_a_path_traversal_reference(tmp_path):
    _write_error_log(tmp_path, "abc123", "traceback text")

    assert logs_reader.read_error_log(tmp_path, "../abc123") is None


def test_read_error_log_returns_the_raw_content(tmp_path):
    _write_error_log(tmp_path, "abc123", "reference: abc123\n\nTraceback...")

    content = logs_reader.read_error_log(tmp_path, "abc123")

    assert content == "reference: abc123\n\nTraceback..."
