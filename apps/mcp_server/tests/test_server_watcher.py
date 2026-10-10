"""Tests for ServerWatcher: crash, removal, error-line batching, cancel, resume."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.capabilities.server_manager.contract import AppInfo, AppListResult, AppLogTextResult
from src.capabilities.server_manager.utils import server_watcher
from src.capabilities.server_manager.utils.server_watcher import ServerWatcher, _line_time
from src.services.watcher import WatcherPhase, WatcherRecord

T0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


def apps(*pairs: tuple[str, str]) -> AppListResult:
    return AppListResult(apps=[AppInfo(name=n, status=s, image="img") for n, s in pairs], message="")


def logs(*lines: str) -> AppLogTextResult:
    text = "\n".join(lines)
    return AppLogTextResult(name="web", lines=len(lines), redactions=0, truncated=False, text=text, message="")


def line(offset_s: float, text: str) -> str:
    return f"{(T0 + timedelta(seconds=offset_s)).strftime('%Y-%m-%dT%H:%M:%S.%f')}Z {text}"


def rig(app_results, log_results=()):
    """A ServerWatcher subclass fed by scripted lists (the last entry repeats), a recording mailer and a movable clock."""
    app_queue, log_queue = list(app_results), list(log_results) or [logs()]
    mails: list[tuple] = []
    now = {"t": T0}

    def take(queue):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def read_logs(name, lines, contains=None):
        result = take(log_queue)
        if contains:
            return logs(*(line for line in result.text.splitlines() if contains.lower() in line.lower()))
        return result

    class Scripted(ServerWatcher):
        backoff_schedule = [(3.0, 0.01)]
        lister = staticmethod(lambda: take(app_queue))
        log_reader = staticmethod(read_logs)
        mailer = staticmethod(lambda *args: mails.append(args) or "sent")
        clock = staticmethod(lambda: now["t"])

    return Scripted, mails, now


def record(tmp_path: Path, cls, key: str) -> WatcherRecord:
    path = tmp_path / cls.__name__ / "instances" / f"{key}.json"
    return WatcherRecord.model_validate_json(path.read_text(encoding="utf-8"))


def make(cls, tmp_path, **changes):
    return cls("web", tmp_path, **{"owner": "alice", "email": "alice@x.io", **changes})


def test_production_schedule_never_times_out():
    watcher = ServerWatcher("web", Path("unused"))

    assert watcher._interval_for_elapsed(599) == 30.0
    assert watcher._interval_for_elapsed(600) == 300.0
    assert watcher._interval_for_elapsed(10**9) == 300.0


def test_line_time_reads_docker_timestamps_with_trimmed_zeros():
    assert _line_time("2026-10-10T12:00:00.5Z boom") == T0 + timedelta(milliseconds=500)
    assert _line_time("2026-10-10T12:00:00.123456789Z boom") == T0 + timedelta(microseconds=123456)
    assert _line_time("2026-10-10T12:00:00Z boom") == T0
    assert _line_time("no timestamp here") is None


def test_a_running_app_sends_no_mail(tmp_path):
    cls, mails, _ = rig([apps(("web", "running"))])
    watcher = make(cls, tmp_path)

    phase, detail = watcher.poll()

    assert phase == WatcherPhase.RUNNING and mails == []
    assert detail["status"] == "running" and detail["checks"] == 1


def test_a_crash_finishes_the_watcher_and_emails_the_owner_once(tmp_path):
    cls, mails, _ = rig([apps(("web", "running")), apps(("web", "exited"))], [logs(line(1, "fatal: out of memory"))])

    make(cls, tmp_path).run()

    saved = record(tmp_path, cls, "web")
    assert saved.phase == WatcherPhase.COMPLETED
    assert saved.detail["reason"] == "crashed" and saved.detail["status"] == "exited"
    assert saved.detail["email_result"] == "sent" and saved.detail["owner"] == "alice"
    ((owner, email, subject, message, details),) = mails
    assert (owner, email, subject) == ("alice", "alice@x.io", "web stopped")
    assert "exited" in message and "out of memory" in details


def test_a_removed_app_finishes_the_watcher_and_emails_the_owner(tmp_path):
    cls, mails, _ = rig([apps(("web", "running")), apps(("other", "running"))])

    make(cls, tmp_path).run()

    saved = record(tmp_path, cls, "web")
    assert saved.phase == WatcherPhase.COMPLETED and saved.detail["reason"] == "removed"
    assert [mail[2] for mail in mails] == ["web was removed"]


def test_new_error_lines_are_emailed_together_and_old_ones_are_ignored(tmp_path):
    cls, mails, _ = rig(
        [apps(("web", "running"))],
        [logs(line(-5, "old error"), line(5, "ERROR first"), line(6, "ERROR second"))],
    )
    watcher = make(cls, tmp_path)

    phase, detail = watcher.poll()

    assert phase == WatcherPhase.RUNNING
    ((_, _, subject, _, details),) = mails
    assert subject == "Errors in web"
    assert "ERROR first" in details and "ERROR second" in details and "old error" not in details
    assert detail["pending"] == [] and detail["email_result"] == "sent"


def test_error_mail_is_limited_to_one_per_hour_and_held_lines_go_out_later(tmp_path):
    first = logs(line(5, "alpha error"))
    both = logs(line(5, "alpha error"), line(650, "bravo error"))
    cls, mails, now = rig([apps(("web", "running"))], [first, both])
    watcher = make(cls, tmp_path)

    watcher.poll()
    assert len(mails) == 1

    now["t"] = T0 + timedelta(seconds=600)
    _, detail = watcher.poll()
    assert len(mails) == 1 and detail["pending"] == [line(650, "bravo error")]

    now["t"] = T0 + timedelta(seconds=3601)
    watcher.poll()
    assert len(mails) == 2
    assert "bravo error" in mails[1][4] and "alpha error" not in mails[1][4]


def test_a_mail_failure_is_recorded_and_does_not_stop_the_watcher(tmp_path):
    cls, _, _ = rig([apps(("web", "exited"))])

    def boom(*args):
        raise RuntimeError("smtp down")

    cls.mailer = staticmethod(boom)
    make(cls, tmp_path).run()

    saved = record(tmp_path, cls, "web")
    assert saved.phase == WatcherPhase.COMPLETED and saved.detail["email_result"].startswith("failed:")


def test_a_cancelled_watcher_does_not_email(tmp_path):
    cls, mails, _ = rig([apps(("web", "exited"))])
    watcher = make(cls, tmp_path)
    watcher.stop()
    watcher._reason = "crashed"
    detail: dict = {}

    watcher.on_completed(detail)

    assert mails == [] and detail["email_result"] == "skipped: cancelled"


def test_resume_rebuilds_the_watcher_with_its_owner_and_held_lines(tmp_path):
    cls, _, _ = rig([apps(("web", "running"))])
    original = make(cls, tmp_path, pending=[line(5, "held error")], last_email_at=T0.isoformat(), checks=4)
    original._save_record(WatcherPhase.RUNNING, {})

    started = cls.resume_all(tmp_path)
    try:
        (watcher,) = started
        assert (watcher.key, watcher.owner, watcher.email) == ("web", "alice", "alice@x.io")
        assert watcher.state_dir == tmp_path and watcher._checks >= 4
        assert cls.is_active("web")
    finally:
        for watcher in started:
            watcher.stop()


def test_cancel_stops_the_watcher_and_removes_its_record(tmp_path):
    cls, _, _ = rig([apps(("web", "running"))])
    make(cls, tmp_path).start()
    path = tmp_path / cls.__name__ / "instances" / "web.json"
    deadline = time.time() + 2
    while not path.exists() and time.time() < deadline:
        time.sleep(0.01)

    cls.cancel(tmp_path, "web")
    time.sleep(0.1)

    assert not cls.is_active("web") and not path.exists()


def test_watch_app_starts_a_watcher_for_the_caller(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(server_watcher, "settings", replace(server_watcher.settings, watchers_dir=tmp_path))
    monkeypatch.setattr(server_watcher.identity_context, "current_username", lambda: "alice")
    monkeypatch.setattr(server_watcher.identity_context, "current_email", lambda: "alice@x.io")
    monkeypatch.setattr(ServerWatcher, "start", lambda self: started.append((self.key, self.owner, self.email, self.state_dir)))

    server_watcher.watch_app("web")

    assert started == [("web", "alice", "alice@x.io", tmp_path)]


def test_pause_watch_cancels_first_and_restores_it_when_the_action_fails(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(server_watcher, "settings", replace(server_watcher.settings, watchers_dir=tmp_path))
    monkeypatch.setattr(ServerWatcher, "is_active", classmethod(lambda cls, key: True))
    monkeypatch.setattr(ServerWatcher, "cancel", classmethod(lambda cls, state_dir, key: calls.append(("cancel", key))))
    monkeypatch.setattr(server_watcher, "watch_app", lambda name: calls.append(("watch", name)))

    def failing():
        calls.append(("action", None))
        raise KeyError("no such app")

    try:
        server_watcher.pause_watch("web", failing)
    except KeyError:
        pass

    assert calls == [("cancel", "web"), ("action", None), ("watch", "web")]


def test_pause_watch_leaves_the_watcher_off_when_the_action_succeeds(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(server_watcher, "settings", replace(server_watcher.settings, watchers_dir=tmp_path))
    monkeypatch.setattr(ServerWatcher, "is_active", classmethod(lambda cls, key: True))
    monkeypatch.setattr(ServerWatcher, "cancel", classmethod(lambda cls, state_dir, key: calls.append(("cancel", key))))
    monkeypatch.setattr(server_watcher, "watch_app", lambda name: calls.append(("watch", name)))

    assert server_watcher.pause_watch("web", lambda: "stopped") == "stopped"
    assert calls == [("cancel", "web")]
