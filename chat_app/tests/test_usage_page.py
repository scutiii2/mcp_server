"""Usage tracker: usage_limits history/report functions and the /usage page."""

from __future__ import annotations

import dataclasses
import sqlite3
from datetime import datetime, timedelta, timezone

from src.pages.Usage import __index__ as usage_index
from src.services import usage_limits
from tests.test_chat_page import _build_chat_test_app, _create_account, _login_as


def _seed(db_path, username, tokens, age, **columns):
    usage_limits.record_usage(
        db_path, username, tokens, ts=(datetime.now(timezone.utc) - age).isoformat(), **columns
    )


def test_history_is_kept_and_only_recent_months_are_reported(tmp_path):
    db = tmp_path / "usage.db"
    _seed(db, "alice", 100, timedelta(days=400))
    _seed(db, "alice", 50, timedelta(hours=1))
    usage_limits.check_limit(db, "alice")  # used to prune rows older than a week

    rows = sqlite3.connect(str(db)).execute("SELECT COUNT(*) FROM token_usage").fetchone()[0]
    assert rows == 2
    assert usage_limits.usage_report(db, "alice", "12m")["total_tokens"] == 50


def test_existing_table_gains_the_new_columns(tmp_path):
    db = tmp_path / "usage.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE token_usage (username TEXT NOT NULL, ts TEXT NOT NULL, tokens INTEGER NOT NULL)")
    conn.execute("INSERT INTO token_usage VALUES ('alice', ?, 7)", (datetime.now(timezone.utc).isoformat(),))
    conn.commit()
    conn.close()

    usage_limits.record_usage(db, "alice", 5, agent="a", model="m")

    assert usage_limits.usage_report(db, "alice", "30d")["total_tokens"] == 12


def test_report_groups_by_agent_and_counts_turns_once(tmp_path):
    db = tmp_path / "usage.db"
    ts = datetime.now(timezone.utc).isoformat()
    usage_limits.record_usage(db, "alice", 40, agent="claude", model="s", input_tokens=30, output_tokens=10,
                              chat_id="c1", ts=ts)
    usage_limits.record_usage(db, "alice", 25, agent="openai", model="g", chat_id="c1", ts=ts)

    report = usage_limits.usage_report(db, "alice", "month")

    assert report["total_tokens"] == 65
    assert report["turns"] == 1
    assert report["chats"] == 1
    assert [row["agent"] for row in report["by_agent"]] == ["claude", "openai"]
    assert report["favorite"]["agent"] == "claude"
    assert report["input_tokens"] == 30 and report["output_tokens"] == 10


def test_get_usage_includes_calendar_month_total(tmp_path):
    db = tmp_path / "usage.db"
    usage_limits.record_usage(db, "alice", 11)
    assert usage_limits.get_usage(db, "alice")["month"]["used"] == 11


def _page_app(tmp_path, monkeypatch):
    app = _build_chat_test_app(tmp_path, monkeypatch)
    monkeypatch.setattr(
        usage_index, "settings", dataclasses.replace(usage_index.settings, usage_db_path=tmp_path / "usage.db")
    )
    return app


def test_page_shows_own_usage_and_ignores_other_user_without_permission(tmp_path, monkeypatch):
    app = _page_app(tmp_path, monkeypatch)
    usage_limits.record_usage(tmp_path / "usage.db", "mine", 1234, agent="claude", model="s")
    usage_limits.record_usage(tmp_path / "usage.db", "other", 9999, agent="openai", model="g")
    client = app.test_client()
    _login_as(client, _create_account(app, "mine", ["chat.access"]))

    body = client.get("/usage/?user=other").get_data(as_text=True)

    assert "1.2k" in body
    assert "openai" not in body
    assert "Viewing" not in body


def test_view_all_permission_shows_another_users_usage(tmp_path, monkeypatch):
    app = _page_app(tmp_path, monkeypatch)
    usage_limits.record_usage(tmp_path / "usage.db", "other", 9999, agent="openai", model="g")
    client = app.test_client()
    _login_as(client, _create_account(app, "boss", ["chat.access", "usage.view_all"]))

    body = client.get("/usage/?user=other").get_data(as_text=True)

    assert "Viewing" in body and "openai" in body


def test_export_downloads_markdown(tmp_path, monkeypatch):
    app = _page_app(tmp_path, monkeypatch)
    usage_limits.record_usage(tmp_path / "usage.db", "mine", 500, agent="claude", model="s")
    client = app.test_client()
    _login_as(client, _create_account(app, "mine", ["chat.access"]))

    response = client.get("/usage/export.md?range=12m")

    assert response.status_code == 200
    assert response.mimetype == "text/markdown"
    assert "attachment" in response.headers["Content-Disposition"]
    text = response.get_data(as_text=True)
    assert "# Token usage - mine" in text
    assert "| Total tokens | 500 |" in text
    assert "| claude | s | 500 |" in text


def test_backfill_fills_agent_on_old_rows_from_chat_messages(tmp_path):
    import json

    from src.services import usage_backfill

    usage_db, chats_db = tmp_path / "usage.db", tmp_path / "chats.db"
    now = datetime.now(timezone.utc)
    usage_limits.record_usage(usage_db, "alice", 500, ts=now.isoformat())
    usage_limits.record_usage(usage_db, "alice", 777, ts=now.isoformat())  # no matching message
    conn = sqlite3.connect(str(chats_db))
    conn.execute("CREATE TABLE chats (id TEXT, username TEXT, title TEXT, messages TEXT)")
    message = {"role": "assistant", "provider_id": "claude", "model": "sonnet", "total_tokens": 500,
               "sent_at": (now + timedelta(seconds=3)).isoformat()}
    conn.execute("INSERT INTO chats VALUES ('c1', 'alice', 't', ?)", (json.dumps([message]),))
    conn.commit()
    conn.close()

    assert usage_backfill.backfill(usage_db, chats_db) == {"candidates": 2, "matched": 1, "defaulted": 0}
    assert usage_limits.usage_report(usage_db, "alice", "month")["by_agent"][0]["agent"] == "unknown"

    usage_backfill.backfill(usage_db, chats_db, apply=True)
    agents = {row["agent"]: row["tokens"] for row in usage_limits.usage_report(usage_db, "alice", "month")["by_agent"]}
    assert agents == {"claude": 500, "unknown": 777}
