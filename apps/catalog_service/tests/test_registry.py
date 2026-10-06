from __future__ import annotations

import threading
import time

import pytest

from src import registry


@pytest.fixture(autouse=True)
def reset_registry():
    registry._entries = []
    registry._status = "scanning"
    yield
    registry._entries = []
    registry._status = "scanning"


def test_load_initial_serves_cached_entries_as_ready(tmp_path):
    cache_path = tmp_path / "catalog_cache.json"
    from src.cache import save_cache_atomic

    save_cache_atomic(cache_path, [{"id": "a.b.c"}])

    registry.load_initial(cache_path)

    assert registry.current() == ("ready", [{"id": "a.b.c"}])


def test_load_initial_leaves_scanning_when_no_cache_exists(tmp_path):
    registry.load_initial(tmp_path / "missing.json")

    assert registry.current() == ("scanning", [])


def test_get_by_id_finds_matching_entry(tmp_path):
    registry._entries = [{"id": "a.b.c"}, {"id": "x.y.z"}]
    registry._status = "ready"

    assert registry.get_by_id("x.y.z") == {"id": "x.y.z"}


def test_get_by_id_returns_none_when_missing():
    registry._entries = [{"id": "a.b.c"}]
    registry._status = "ready"

    assert registry.get_by_id("nope") is None


def test_refresh_sets_scanning_immediately_and_ready_after_background_scan(
    monkeypatch, tmp_path
):
    started = threading.Event()
    release = threading.Event()

    def fake_scan_project(project, root):
        started.set()
        release.wait(timeout=2)
        return []

    monkeypatch.setattr(registry.scanner, "scan_project", fake_scan_project)
    cache_path = tmp_path / "catalog_cache.json"

    registry.refresh([("chat_app", tmp_path)], cache_path)

    assert registry.current()[0] == "scanning"
    assert started.wait(timeout=2)
    release.set()

    for _ in range(100):
        if registry.current()[0] == "ready":
            break
        time.sleep(0.02)

    assert registry.current() == ("ready", [])
    assert cache_path.exists()


def test_refresh_recovers_status_to_ready_when_scan_raises(monkeypatch, tmp_path):
    # Regression test for Finding 3(b): a scan failure must never wedge the
    # registry's status at "scanning" forever. Previously-served entries
    # must also survive a failed refresh (not be cleared to []).
    registry._entries = [{"id": "previous.entry"}]
    registry._status = "ready"

    started = threading.Event()
    finished = threading.Event()

    def failing_scan_project(project, root):
        started.set()
        raise RuntimeError("simulated scan failure")

    monkeypatch.setattr(registry.scanner, "scan_project", failing_scan_project)

    original_run_refresh = registry._run_refresh

    def wrapped_run_refresh(*args, **kwargs):
        try:
            original_run_refresh(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(registry, "_run_refresh", wrapped_run_refresh)

    cache_path = tmp_path / "catalog_cache.json"
    registry.refresh([("chat_app", tmp_path)], cache_path)

    assert started.wait(timeout=2)
    assert finished.wait(timeout=2)

    # The thread must not have died silently mid-scan without ever
    # flipping status back - it must land on "ready", not stay wedged on
    # "scanning".
    assert registry.current() == ("ready", [{"id": "previous.entry"}])
