from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.services.watcher import JobWatcher, WatcherPhase, WatcherRecord


class _FakeWatcher(JobWatcher):
    """Test double: poll() returns whatever the test queues up next."""

    backoff_schedule = [(0.3, 0.05), (0.6, 0.1)]  # short schedule for fast tests

    def __init__(self, key: str, state_dir: Path, results: list[tuple[WatcherPhase, dict]], started_at: str | None = None):
        super().__init__(key=key, state_dir=state_dir, started_at=started_at)
        self._results = list(results)
        self.completed_detail: dict | None = None
        self.state_changes: list[tuple[WatcherPhase | None, WatcherPhase]] = []

    def poll(self):
        if not self._results:
            return WatcherPhase.RUNNING, {}
        return self._results.pop(0)

    def on_completed(self, detail):
        self.completed_detail = detail

    def on_state_change(self, old, new, detail):
        self.state_changes.append((old, new))

    @classmethod
    def from_record(cls, record: WatcherRecord) -> "_FakeWatcher":
        return cls(key=record.key, state_dir=Path("unused"), results=[], started_at=record.started_at)


def test_interval_for_elapsed_follows_schedule(tmp_path):
    watcher = _FakeWatcher("k", tmp_path, [])
    assert watcher._interval_for_elapsed(0.0) == 0.05
    assert watcher._interval_for_elapsed(0.3) == 0.1
    assert watcher._interval_for_elapsed(0.59) == 0.1
    assert watcher._interval_for_elapsed(0.6) is None  # past last cutoff -> timed out


def test_run_stops_on_completed_and_calls_on_completed(tmp_path):
    watcher = _FakeWatcher(
        "job1", tmp_path,
        results=[(WatcherPhase.RUNNING, {"n": 1}), (WatcherPhase.COMPLETED, {"n": 2})],
    )
    watcher.run()  # runs synchronously to completion since results is finite and terminal

    assert watcher.completed_detail == {"n": 2}
    assert (WatcherPhase.RUNNING, WatcherPhase.COMPLETED) in watcher.state_changes

    record = WatcherRecord.model_validate_json(
        (tmp_path / "_FakeWatcher" / "instances" / "job1.json").read_text(encoding="utf-8")
    )
    assert record.phase == WatcherPhase.COMPLETED
    assert record.detail == {"n": 2}


def test_run_times_out_when_never_terminal(tmp_path):
    watcher = _FakeWatcher("job2", tmp_path, results=[])  # poll() always returns RUNNING
    watcher.run()

    record = WatcherRecord.model_validate_json(
        (tmp_path / "_FakeWatcher" / "instances" / "job2.json").read_text(encoding="utf-8")
    )
    assert record.phase == WatcherPhase.TIMED_OUT


def test_poll_error_is_swallowed_and_retried(tmp_path):
    calls = {"n": 0}

    class _FlakyWatcher(_FakeWatcher):
        def poll(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient RFC error")
            return WatcherPhase.COMPLETED, {"ok": True}

    watcher = _FlakyWatcher("job3", tmp_path, results=[])
    watcher.run()

    assert calls["n"] == 2
    assert watcher.completed_detail == {"ok": True}


def test_resumed_watcher_continues_elapsed_time_from_record(tmp_path):
    """Verify that resumed watchers preserve elapsed time from their original
    start, so backoff/timeout clock continues counting instead of resetting."""
    # Create a record with started_at far enough in the past to exceed the schedule's last cutoff (0.6 seconds)
    now = datetime.now(timezone.utc)
    old_start = (now - timedelta(seconds=1.0)).isoformat()

    record = WatcherRecord(
        key="old_job",
        phase=WatcherPhase.RUNNING,
        started_at=old_start,
        last_polled_at=now.isoformat(),
        detail={},
    )

    # Reconstruct the watcher from the record
    watcher = _FakeWatcher.from_record(record)
    watcher.state_dir = tmp_path

    # Run it - it should immediately timeout because elapsed time (>1s) is past the schedule cutoff (0.6s)
    watcher.run()

    # Verify it timed out instead of running polls
    persisted = WatcherRecord.model_validate_json(
        (tmp_path / "_FakeWatcher" / "instances" / "old_job.json").read_text(encoding="utf-8")
    )
    assert persisted.phase == WatcherPhase.TIMED_OUT
    # started_at should be preserved from the record, not reset to "now"
    assert persisted.started_at == old_start


def test_state_path_sanitizes_colons_in_key(tmp_path):
    watcher = _FakeWatcher("sid:job:count", tmp_path, results=[(WatcherPhase.COMPLETED, {"x": 1})])
    watcher.run()
    saved_files = list((tmp_path / "_FakeWatcher" / "instances").glob("*.json"))
    assert len(saved_files) == 1
    assert ":" not in saved_files[0].name
    # resume_all must be able to find and reload it despite the sanitized filename
    resumed = _FakeWatcher.resume_all(tmp_path)
    # this key's phase is COMPLETED (terminal), so resume_all should NOT restart it
    assert resumed == []
