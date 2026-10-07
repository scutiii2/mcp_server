"""Tests for the watch capability's domain logic: create, list, cancel, limits."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from src.capabilities.watchers import domain
from src.capabilities.watchers.utils.spec import WatchSpec
from src.capabilities.watchers.utils.user_watcher import UserWatcher
from src.services import watcher_recipients
from src.services.watcher import WatcherPhase, WatcherRecord


class NoStart(UserWatcher):
    """Saves the first record like a real start, without spawning a polling thread."""

    def start(self) -> None:
        self._save_record(WatcherPhase.RUNNING, {})


def create(tmp_path, owner="alice", email="alice@x.io", *, kind="url", target="https://example.com/", expect="up", contains="", label="", list_apps=None):
    return domain.create_watcher(
        tmp_path, owner, email, kind, target, expect, contains, label, factory=NoStart, list_apps=list_apps
    )


def finished(tmp_path, key, owner, last_polled_at, phase=WatcherPhase.COMPLETED):
    spec = WatchSpec("url", "https://example.com/", "up", "", "", owner, "")
    path = tmp_path / "NoStart" / "instances" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = WatcherRecord(key=key, phase=phase, started_at=last_polled_at, last_polled_at=last_polled_at, detail=spec.to_detail())
    path.write_text(record.model_dump_json(), encoding="utf-8")
    watcher_recipients.set_recipients(tmp_path, "NoStart", key, [f"{owner}@x.io"])


def test_create_starts_a_watcher_stores_the_owner_email_and_explains_it(tmp_path):
    result = create(tmp_path)

    assert result.key.startswith("w-") and len(result.key) == 10
    assert "https://example.com/ to be reachable" in result.message
    assert "every 30 seconds" in result.message and "24 hours" in result.message and "alice@x.io" in result.message
    assert watcher_recipients.get_recipients(tmp_path, "NoStart", result.key) == ["alice@x.io"]
    listed = domain.list_watchers(tmp_path, "alice", factory=NoStart)
    assert [row.key for row in listed.watchers] == [result.key]
    assert listed.watchers[0].detail["owner"] == "alice" and listed.watchers[0].phase == "running"


def test_create_without_an_email_says_no_email_will_be_sent(tmp_path):
    result = create(tmp_path, email="")

    assert "no email" in result.message.lower()
    assert watcher_recipients.get_recipients(tmp_path, "NoStart", result.key) == []


def test_create_refuses_bad_input_and_an_unidentified_caller(tmp_path):
    with pytest.raises(ValueError, match="not identified"):
        create(tmp_path, owner="")
    with pytest.raises(ValueError, match="kind must be"):
        create(tmp_path, kind="ping")
    assert domain.list_watchers(tmp_path, "alice", factory=NoStart).watchers == []


def test_per_owner_and_total_running_limits(tmp_path, monkeypatch):
    for _ in range(domain.MAX_PER_OWNER):
        create(tmp_path)
    with pytest.raises(ValueError, match="5 running watchers"):
        create(tmp_path)
    create(tmp_path, owner="bob", email="b@x.io")

    monkeypatch.setattr(domain, "MAX_TOTAL", 6)
    with pytest.raises(ValueError, match="busy"):
        create(tmp_path, owner="carol", email="c@x.io")


def test_finished_watchers_do_not_count_toward_the_running_limit(tmp_path):
    for index in range(domain.MAX_PER_OWNER):
        finished(tmp_path, f"w-0000000{index}", "alice", f"2026-01-0{index + 1}T00:00:00+00:00")

    create(tmp_path)


def test_only_the_newest_finished_records_are_kept_per_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(domain, "MAX_FINISHED", 2)
    finished(tmp_path, "w-00000001", "alice", "2026-01-01T00:00:00+00:00")
    finished(tmp_path, "w-00000002", "alice", "2026-01-02T00:00:00+00:00")
    finished(tmp_path, "w-00000003", "alice", "2026-01-03T00:00:00+00:00")
    finished(tmp_path, "w-00000009", "bob", "2026-01-01T00:00:00+00:00")

    create(tmp_path)

    keys = {row.key for row in domain.list_watchers(tmp_path, "alice", factory=NoStart).watchers}
    assert "w-00000001" not in keys and {"w-00000002", "w-00000003"} <= keys
    assert watcher_recipients.get_recipients(tmp_path, "NoStart", "w-00000001") == []
    assert [row.key for row in domain.list_watchers(tmp_path, "bob", factory=NoStart).watchers] == ["w-00000009"]


def fake_apps(*pairs):
    return lambda: SimpleNamespace(apps=[SimpleNamespace(name=n, status=s) for n, s in pairs])


def test_an_app_watcher_needs_a_known_app_and_available_docker(tmp_path):
    ok = create(tmp_path, kind="app", target="web", list_apps=fake_apps(("web", "exited")))
    assert "app web to be running" in ok.message

    with pytest.raises(ValueError, match="No app named 'ghost'.*web"):
        create(tmp_path, kind="app", target="ghost", list_apps=fake_apps(("web", "running")))

    def no_docker():
        raise RuntimeError("cannot connect to the Docker daemon")

    with pytest.raises(ValueError, match="Docker is not available.*cannot connect"):
        create(tmp_path, kind="app", target="web", list_apps=no_docker)


def test_list_is_newest_first_and_only_the_owners(tmp_path):
    finished(tmp_path, "w-00000001", "alice", "2026-01-01T00:00:00+00:00")
    finished(tmp_path, "w-00000002", "alice", "2026-02-01T00:00:00+00:00")
    finished(tmp_path, "w-00000003", "bob", "2026-03-01T00:00:00+00:00")

    result = domain.list_watchers(tmp_path, "alice", factory=NoStart)

    assert [row.key for row in result.watchers] == ["w-00000002", "w-00000001"]
    assert result.watchers[0].recipients == ["alice@x.io"] and result.watchers[0].phase == "completed"
    assert "2 watchers" in result.message
    with pytest.raises(ValueError, match="not identified"):
        domain.list_watchers(tmp_path, "", factory=NoStart)


def test_cancel_removes_the_record_and_recipients_of_the_owners_own_watcher(tmp_path):
    key = create(tmp_path).key

    result = domain.cancel_watcher(tmp_path, "alice", key, factory=NoStart)

    assert key in result.message and domain.list_watchers(tmp_path, "alice", factory=NoStart).watchers == []
    assert watcher_recipients.get_recipients(tmp_path, "NoStart", key) == []


def test_cancel_of_a_foreign_unknown_or_malformed_key_gives_the_same_answer(tmp_path):
    key = create(tmp_path).key

    for owner, bad in (("bob", key), ("alice", "w-deadbeef"), ("alice", "../../etc/passwd"), ("alice", "")):
        with pytest.raises(ValueError, match="No such watcher"):
            domain.cancel_watcher(tmp_path, owner, bad, factory=NoStart)
    assert [row.key for row in domain.list_watchers(tmp_path, "alice", factory=NoStart).watchers] == [key]
    with pytest.raises(ValueError, match="not identified"):
        domain.cancel_watcher(tmp_path, "", key, factory=NoStart)


class Silent(UserWatcher):
    """Like the real start: no record is written and no thread runs."""

    def start(self) -> None:
        pass


class Exploding(UserWatcher):
    def start(self) -> None:
        raise RuntimeError("cannot start")


def create_with(factory, tmp_path, owner="alice"):
    return domain.create_watcher(tmp_path, owner, f"{owner}@x.io", "url", "https://example.com/", factory=factory)


def test_the_first_record_exists_as_soon_as_create_returns_so_limits_hold(tmp_path):
    key = create_with(Silent, tmp_path).key

    assert [row.key for row in domain.list_watchers(tmp_path, "alice", factory=Silent).watchers] == [key]
    for _ in range(domain.MAX_PER_OWNER - 1):
        create_with(Silent, tmp_path)
    with pytest.raises(ValueError, match="5 running watchers"):
        create_with(Silent, tmp_path)


def test_concurrent_creates_cannot_exceed_the_per_owner_limit(tmp_path):
    outcomes = []

    def worker():
        try:
            create_with(Silent, tmp_path)
            outcomes.append("ok")
        except ValueError as error:
            outcomes.append(str(error))

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("ok") == domain.MAX_PER_OWNER
    assert all("5 running watchers" in o for o in outcomes if o != "ok")


def test_a_failed_start_leaves_no_record_or_recipients(tmp_path):
    with pytest.raises(RuntimeError, match="cannot start"):
        create_with(Exploding, tmp_path)

    assert domain.list_watchers(tmp_path, "alice", factory=Exploding).watchers == []
    folder = tmp_path / "Exploding"
    assert not list(folder.rglob("*.json")) or all(
        watcher_recipients.get_recipients(tmp_path, "Exploding", p.stem) == [] for p in folder.rglob("w-*.json")
    )


def test_a_permanently_corrupt_record_is_skipped(tmp_path):
    finished(tmp_path, "w-00000001", "alice", "2026-01-01T00:00:00+00:00")
    (tmp_path / "NoStart" / "instances" / "w-00000002.json").write_text("{not json", encoding="utf-8")

    assert [row.key for row in domain.list_watchers(tmp_path, "alice", factory=NoStart).watchers] == ["w-00000001"]
