"""Tests for UserWatcher: completion, timeout, notification outcomes, cancel, resume."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from src.capabilities.watchers.utils.checks import CheckResult
from src.capabilities.watchers.utils.spec import WatchSpec
from src.capabilities.watchers.utils.user_watcher import UserWatcher
from src.services.watcher import WatcherPhase, WatcherRecord

DOWN = CheckResult(False, {"reachable": False})
UP = CheckResult(True, {"reachable": True, "status": 200})
UNKNOWN = CheckResult(None, {"found": False})


def spec(**changes) -> WatchSpec:
    values = dict(kind="url", target="https://example.com/", expect="up", contains="", label="Blog", owner="alice", email="alice@x.io")
    return WatchSpec(**{**values, **changes})


def scripted(results, outcome="sent", schedule=((3.0, 0.01),)):
    """A UserWatcher subclass whose checks follow `results` (then stay down) and whose notifications are recorded."""
    queue = list(results)
    sent: list[tuple] = []

    def notifier(watch_spec, key, event, checks):
        sent.append((key, event, checks))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    class Scripted(UserWatcher):
        backoff_schedule = list(schedule)
        checker = staticmethod(lambda watch_spec: queue.pop(0) if queue else DOWN)

    Scripted.notifier = staticmethod(notifier)
    return Scripted, sent


def record(tmp_path: Path, cls, key: str) -> WatcherRecord:
    return WatcherRecord.model_validate_json((tmp_path / cls.__name__ / "instances" / f"{key}.json").read_text(encoding="utf-8"))


def test_production_schedule_is_every_30s_then_every_5_minutes():
    watcher = UserWatcher("w-1", Path("unused"), spec())

    assert UserWatcher.backoff_schedule == [(600.0, 30.0), (86400.0, 300.0)]
    assert watcher._interval_for_elapsed(599) == 30.0
    assert watcher._interval_for_elapsed(600) == 300.0
    assert watcher._interval_for_elapsed(86400) is None


def test_completes_when_the_check_matches_expect_up_and_notifies_once(tmp_path):
    cls, sent = scripted([DOWN, DOWN, UP])
    watcher = cls("w-k1", tmp_path, spec())

    watcher.run()

    saved = record(tmp_path, cls, "w-k1")
    assert saved.phase == WatcherPhase.COMPLETED
    assert sent == [("w-k1", "met", 3)]
    assert saved.detail["email_result"] == "sent" and saved.detail["checks"] == 3
    assert saved.detail["email"] == "alice@x.io"
    assert saved.detail["owner"] == "alice" and saved.detail["target"] == "https://example.com/"
    assert saved.detail["last_check"] == UP.detail


def test_expect_down_completes_on_a_down_check(tmp_path):
    cls, sent = scripted([UP, DOWN])

    cls("w-k2", tmp_path, spec(expect="down")).run()

    assert record(tmp_path, cls, "w-k2").phase == WatcherPhase.COMPLETED and sent == [("w-k2", "met", 2)]


def test_an_unknown_result_never_matches_and_the_watcher_times_out_with_an_email(tmp_path):
    cls, sent = scripted([UNKNOWN] * 1000, schedule=((0.3, 0.02),))

    cls("w-k3", tmp_path, spec(kind="app", target="ghost")).run()

    saved = record(tmp_path, cls, "w-k3")
    assert saved.phase == WatcherPhase.TIMED_OUT
    assert [(event) for _key, event, _n in sent] == ["timed_out"]
    assert saved.detail["email_result"] == "sent" and saved.detail["owner"] == "alice"
    assert saved.detail["email"] == "alice@x.io"


def test_the_email_outcome_is_recorded_as_given(tmp_path):
    cls, _ = scripted([UP], outcome="skipped: email is not configured")

    cls("w-k4", tmp_path, spec()).run()

    assert record(tmp_path, cls, "w-k4").detail["email_result"] == "skipped: email is not configured"


def test_a_notifier_that_raises_is_recorded_and_the_watcher_still_completes(tmp_path):
    cls, _ = scripted([UP], outcome=RuntimeError("smtp down"))

    cls("w-k5", tmp_path, spec()).run()

    saved = record(tmp_path, cls, "w-k5")
    assert saved.phase == WatcherPhase.COMPLETED
    assert saved.detail["email_result"].startswith("failed: RuntimeError") and "smtp down" in saved.detail["email_result"]


def test_a_cancelled_watcher_never_sends_mail(tmp_path):
    cls, sent = scripted([])
    watcher = cls("w-c1", tmp_path, spec())
    watcher._stop_event.set()
    done: dict = {}
    timed_out: dict = {}

    watcher.on_completed(done)
    watcher.on_state_change(WatcherPhase.RUNNING, WatcherPhase.TIMED_OUT, timed_out)

    assert sent == []
    assert done["email_result"] == "skipped: cancelled" and timed_out["email_result"] == "skipped: cancelled"


def test_from_record_restores_the_spec_the_poll_count_and_start_time(tmp_path):
    cls, _ = scripted([])
    original = cls("w-k6", tmp_path, spec(contains="", label="Blog"), started_at="2026-01-01T00:00:00+00:00", checks=4)
    original._save_record(WatcherPhase.RUNNING, {"checks": 4})

    rebuilt = cls.from_record(record(tmp_path, cls, "w-k6"))

    assert rebuilt.spec == original.spec and rebuilt._checks == 4
    assert rebuilt._started_at == "2026-01-01T00:00:00+00:00"


def test_saves_always_carry_the_spec_even_for_an_empty_detail(tmp_path):
    cls, _ = scripted([])
    watcher = cls("w-k7", tmp_path, spec())

    watcher._save_record(WatcherPhase.RUNNING, {})

    assert record(tmp_path, cls, "w-k7").detail["owner"] == "alice"


def test_a_cancelled_watcher_never_writes_again(tmp_path):
    cls, _ = scripted([])
    watcher = cls("w-k8", tmp_path, spec())
    watcher._stop_event.set()

    watcher._save_record(WatcherPhase.RUNNING, {})

    assert not (tmp_path / cls.__name__ / "instances" / "w-k8.json").exists()


def test_cancel_stops_the_thread_and_removes_the_record(tmp_path):
    cls, _ = scripted([], schedule=((30, 0.05),))
    watcher = cls("w-k9", tmp_path, spec())
    watcher.start()
    path = tmp_path / cls.__name__ / "instances" / "w-k9.json"
    for _ in range(40):
        if path.exists():
            break
        time.sleep(0.05)
    assert path.exists()

    cls.cancel(tmp_path, "w-k9")
    for thread in threading.enumerate():
        if thread.name == f"{cls.__name__}_w-k9":
            thread.join(2)
    time.sleep(0.2)

    assert not path.exists()
    assert "w-k9" not in UserWatcher._active.get(cls.__name__, {})


def test_cancel_of_an_unknown_key_is_harmless(tmp_path):
    cls, _ = scripted([])

    cls.cancel(tmp_path, "w-none")


def test_resume_all_restarts_only_running_records_with_their_spec(tmp_path):
    cls, _ = scripted([], schedule=((30, 0.05),))
    running = cls("w-r1", tmp_path, spec(label="one"))
    running._save_record(WatcherPhase.RUNNING, {})
    finished = cls("w-r2", tmp_path, spec(label="two"))
    finished._save_record(WatcherPhase.COMPLETED, {})

    resumed = cls.resume_all(tmp_path)

    try:
        assert [w.key for w in resumed] == ["w-r1"]
        assert resumed[0].spec.label == "one"
    finally:
        cls.cancel(tmp_path, "w-r1")
        for thread in threading.enumerate():
            if thread.name == f"{cls.__name__}_w-r1":
                thread.join(2)
