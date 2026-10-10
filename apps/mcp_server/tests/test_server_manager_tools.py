"""The server_manager tools start, pause and stop the app's ServerWatcher."""

from __future__ import annotations

import asyncio

import pytest

from src.capabilities.server_manager import tool
from src.capabilities.server_manager.contract import AppActionResult


@pytest.fixture
def calls(monkeypatch):
    log: list[tuple] = []

    def result(action):
        return lambda name: log.append((action, name)) or AppActionResult(name=name, action=action, status="x", message="m")

    monkeypatch.setattr(tool.domain, "start_app", result("start"))
    monkeypatch.setattr(tool.domain, "stop_app", result("stop"))
    monkeypatch.setattr(tool.domain, "restart_app", result("restart"))
    monkeypatch.setattr(tool, "watch_app", lambda name: log.append(("watch", name)))
    monkeypatch.setattr(tool, "pause_watch", lambda name, action: (log.append(("pause", name)), action())[1])
    return log


def test_start_app_starts_the_app_then_its_watcher(calls):
    asyncio.run(tool.tool_srv_startApp("web"))

    assert calls == [("start", "web"), ("watch", "web")]


def test_stop_app_stops_inside_a_paused_watch(calls):
    asyncio.run(tool.tool_srv_stopApp("web"))

    assert calls == [("pause", "web"), ("stop", "web")]


def test_restart_app_restarts_inside_a_paused_watch_then_watches_again(calls):
    asyncio.run(tool.tool_srv_restartApp("web"))

    assert calls == [("pause", "web"), ("restart", "web"), ("watch", "web")]


def test_a_failed_start_starts_no_watcher(calls, monkeypatch):
    def failing(name):
        raise KeyError("no such app")

    monkeypatch.setattr(tool.domain, "start_app", failing)

    with pytest.raises(KeyError):
        asyncio.run(tool.tool_srv_startApp("ghost"))

    assert calls == []
