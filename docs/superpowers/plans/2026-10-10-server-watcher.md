# ServerWatcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `JobWatcher` the shared base for capability-owned background workflows, add `ServerWatcher` as its first child (owned by `server_manager`), then remove the user-facing `watchers` capability.

**Architecture:** `ServerWatcher` is started by the `server_manager` tool layer after `tool_srv_startApp` / `tool_srv_restartApp`, paused around stop/restart, and resumed at server start. It polls `domain.list_apps()` and `domain.read_app_logs()` directly (no MCP round trip) and emails the owner through the shared Email capability. `list_apps` reports a `watched` flag from the base class's registry.

**Tech Stack:** Python 3.11+, pydantic, docker SDK, pytest. Tests run from `apps/mcp_server` with `.venv_mcp/Scripts/python -m pytest <path> -q`.

**Spec:** `docs/superpowers/specs/2026-10-10-server-watcher-design.md`

## Global Constraints

- The server_manager capability id is `server` (tool prefix `srv`). Registry checks use `"server"`.
- Poll schedule: every 30 s for the first 600 s, then every 300 s, no time limit. Use `float("inf")` as the last cutoff (no change needed in `_interval_for_elapsed`). This replaces the spec's "None cutoff" wording.
- Error-line emails: at most one per app per 3600 s; lines found during the cool-down are held and sent together.
- Crash = app listed and status is not `running` (`exited`, `dead`, `restarting`, `paused`). Removed = app not listed. Both finish the watcher and send one email.
- Mail goes to the owner's own address (`identity_context.current_email()` at start), never a tool argument. A mail problem never stops a watcher.
- State directory: `settings.watchers_dir` (`MCP_WATCHERS_DIR`), kept for all job watchers.
- Log text is already masked by `redact()`; never store or send unmasked log text.
- `services/watcher_recipients.py` stays: `capabilities/email/domain.py` imports `parse_recipients` from it.
- `apps/server_launcher` mentions "liveness watcher": a different thing. Do not touch it.
- ember_web changes: propose each step to the user and wait for approval before editing (user workflow rule).
- Commits end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Stage only the files each task lists; the repo has unrelated uncommitted changes.

---

## Task 1: Base class gains cancel, is_active, resume fix

**Files:**
- Modify: `apps/mcp_server/src/services/watcher.py`
- Test: `apps/mcp_server/tests/test_watcher.py`

**Interfaces:**
- Produces (on `JobWatcher`):
  - `@classmethod is_active(cls, key: str) -> bool`
  - `@classmethod cancel(cls, state_dir: Path, key: str) -> None` (stops the running watcher, deletes its record)
  - `@classmethod _record_path(cls, state_dir: Path, key: str) -> Path`
  - `resume_all` sets `watcher.state_dir = state_dir` on each rebuilt watcher
  - `_save_record` writes nothing once the stop event is set

- [ ] **Step 1: Write the failing tests**

Add `import time` to the imports of `apps/mcp_server/tests/test_watcher.py`, then append:

```python
def test_is_active_follows_start_and_cancel(tmp_path):
    watcher = _FakeWatcher("job-a", tmp_path, [])
    assert not _FakeWatcher.is_active("job-a")

    watcher.start()
    assert _FakeWatcher.is_active("job-a")

    _FakeWatcher.cancel(tmp_path, "job-a")
    assert not _FakeWatcher.is_active("job-a")


def test_cancel_deletes_the_record_and_it_does_not_come_back(tmp_path):
    watcher = _FakeWatcher("job-b", tmp_path, [])
    watcher.start()
    path = tmp_path / "_FakeWatcher" / "instances" / "job-b.json"
    deadline = time.time() + 2
    while not path.exists() and time.time() < deadline:
        time.sleep(0.01)
    assert path.exists()

    _FakeWatcher.cancel(tmp_path, "job-b")
    time.sleep(0.2)

    assert not path.exists()


def test_a_stopped_watcher_does_not_write_its_record(tmp_path):
    watcher = _FakeWatcher("job-c", tmp_path, [])
    watcher.stop()

    watcher._save_record(WatcherPhase.RUNNING, {})

    assert not watcher._state_path().exists()


def test_resume_all_points_rebuilt_watchers_at_the_real_state_directory(tmp_path):
    _FakeWatcher("job-d", tmp_path, [])._save_record(WatcherPhase.RUNNING, {})

    started = _FakeWatcher.resume_all(tmp_path)
    try:
        assert [watcher.state_dir for watcher in started] == [tmp_path]
    finally:
        for watcher in started:
            watcher.stop()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_watcher.py -q`
Expected: 4 FAIL (`AttributeError: ... has no attribute 'is_active'` / `cancel`, and the resume test shows `Path('unused')`).

- [ ] **Step 3: Implement**

In `apps/mcp_server/src/services/watcher.py` replace `_state_path` and `_save_record`:

```python
    @classmethod
    def _record_path(cls, state_dir: Path, key: str) -> Path:
        safe_key = key.replace("/", "_").replace("\\", "_").replace(":", "_")
        return state_dir / cls.__name__ / "instances" / f"{safe_key}.json"

    def _state_path(self) -> Path:
        return self._record_path(self.state_dir, self.key)

    def _save_record(self, phase: WatcherPhase, detail: dict[str, Any]) -> None:
        if self._stop_event.is_set():
            return  # cancelled: a poll still in flight must not bring the record back
        record = WatcherRecord(
            key=self.key, phase=phase, started_at=self._started_at,
            last_polled_at=_now_iso(), detail=detail,
        )
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
```

Add after `stop`/`_deregister`:

```python
    @classmethod
    def is_active(cls, key: str) -> bool:
        """True while a watcher of this class is running under `key`."""
        with cls._active_lock:
            return key in cls._active.get(cls.__name__, {})

    @classmethod
    def cancel(cls, state_dir: Path, key: str) -> None:
        """Stops the running watcher with this key, if any, and deletes its record."""
        with cls._active_lock:
            event = cls._active.get(cls.__name__, {}).pop(key, None)
        if event is not None:
            event.set()
        cls._record_path(state_dir, key).unlink(missing_ok=True)
```

In `resume_all`, after `watcher = cls.from_record(record)` add `watcher.state_dir = state_dir`.

Change the `on_state_change` docstring to: `"""Called after every poll where phase changed. Default: no-op. Use it for notifications."""`

- [ ] **Step 4: Run to verify they pass**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_watcher.py tests/test_user_watcher.py tests/test_watch_domain.py -q`
Expected: all PASS (UserWatcher keeps its own `cancel` and `_resume_dir`; it still works).

- [ ] **Step 5: Commit**

```bash
git add apps/mcp_server/src/services/watcher.py apps/mcp_server/tests/test_watcher.py
git commit -m "feat(mcp-server): JobWatcher cancel, is_active and safe resume"
```

---

## Task 2: Owner email helper for server_manager

**Files:**
- Create: `apps/mcp_server/src/capabilities/server_manager/utils/notify.py`
- Test: `apps/mcp_server/tests/test_server_watcher_notify.py`

**Interfaces:**
- Produces: `send_owner_email(owner: str, email: str, subject: str, message: str, details_html: str, *, config_path: Path | None = None, sender=deliver_email) -> str` returning `"sent"`, `"skipped: <reason>"` or `"failed: <reason>"`. Never raises.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the owner email helper used by ServerWatcher."""

from __future__ import annotations

from src.capabilities.server_manager.utils import notify
from src.services.email_delivery import EmailUnavailable


def test_sends_one_notification_to_the_owner_address():
    sent = []

    def sender(to, subject, body_text, **kwargs):
        sent.append((to, subject, body_text, kwargs))
        return "message-id"

    result = notify.send_owner_email("alice", "alice@x.io", "web stopped", "It stopped.", "<p>d</p>", sender=sender)

    assert result == "sent"
    ((to, subject, body_text, kwargs),) = sent
    assert to == ["alice@x.io"] and subject == "web stopped" and body_text is None
    assert kwargs["owner"] == "alice" and kwargs["capability_alias"] == "server"
    assert "web stopped" in kwargs["body_html"] and "It stopped." in kwargs["body_html"]


def test_no_address_means_skipped_without_calling_the_sender():
    def sender(*args, **kwargs):
        raise AssertionError("must not send")

    result = notify.send_owner_email("alice", "", "s", "m", "", sender=sender)

    assert result.startswith("skipped:")


def test_unavailable_email_is_skipped_with_the_reason():
    def sender(*args, **kwargs):
        raise EmailUnavailable("email capability is disabled")

    assert notify.send_owner_email("a", "a@x.io", "s", "m", "", sender=sender) == "skipped: email capability is disabled"


def test_any_other_error_is_reported_without_its_contents():
    def sender(*args, **kwargs):
        raise RuntimeError("smtp password hunter2")

    result = notify.send_owner_email("a", "a@x.io", "s", "m", "", sender=sender)

    assert result.startswith("failed:") and "hunter2" not in result
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_server_watcher_notify.py -q`
Expected: FAIL (`ImportError: cannot import name 'notify'`).

- [ ] **Step 3: Implement**

`apps/mcp_server/src/capabilities/server_manager/utils/notify.py`:

```python
"""The one kind of email a ServerWatcher sends, to its owner only.

Returns an outcome string instead of raising, because a watcher thread must keep
going whether or not mail works: "sent", "skipped: <reason>" or "failed: <reason>".
The shared Email capability owns the enabled check, configuration and SMTP delivery.
"""

from __future__ import annotations

from pathlib import Path

from src.services.email_delivery import EmailUnavailable, deliver_email
from src.services.email_render import render_email_template


def send_owner_email(
    owner: str,
    email: str,
    subject: str,
    message: str,
    details_html: str,
    *,
    config_path: Path | None = None,
    sender=deliver_email,
) -> str:
    """Emails `email` (the requester's own address) with the `notification` template."""
    if not email:
        return "skipped: no email address is known for the requester"
    body = render_email_template("notification", title=subject, message=message, details_html=details_html)
    try:
        sender([email], subject, None, body_html=body, capability_alias="server",
               config_path=config_path, owner=owner)
    except EmailUnavailable as error:
        return f"skipped: {error}"[:300]
    except Exception:  # mail trouble is reported without raw exception contents
        return "failed: email delivery failed; check MCP email configuration and delivery status"
    return "sent"
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_server_watcher_notify.py -q`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/mcp_server/src/capabilities/server_manager/utils/notify.py apps/mcp_server/tests/test_server_watcher_notify.py
git commit -m "feat(mcp-server): owner email helper for server watcher"
```

---

## Task 3: ServerWatcher

**Files:**
- Create: `apps/mcp_server/src/capabilities/server_manager/utils/server_watcher.py`
- Test: `apps/mcp_server/tests/test_server_watcher.py`

**Interfaces:**
- Consumes: `JobWatcher`, `WatcherPhase`, `WatcherRecord` (Task 1); `notify.send_owner_email` (Task 2); `domain.list_apps() -> AppListResult`, `domain.read_app_logs(name, lines, contains) -> AppLogTextResult` (existing, imported lazily to avoid a cycle with Task 4).
- Produces: `class ServerWatcher(JobWatcher)` with constructor `ServerWatcher(key, state_dir, owner="", email="", started_at=None, since=None, pending=None, last_email_at="", checks=0)`; `watch_app(name: str) -> None`; `pause_watch(name: str, action: Callable[[], T]) -> T`.

Behaviour notes for the implementer:
- `key` is the container name. Replaceable collaborators are class attributes (`lister`, `log_reader`, `mailer`, `clock`) so tests inject fakes, as `UserWatcher` does.
- `poll()` keeps its state on the instance and returns `self._detail()`. `_save_record` merges `_detail()` so even the initial `{}` save carries owner and email, which is what makes resume work.
- `since` is an ISO time. Only log lines stamped after it count as new, so lines from before the watcher began (container logs outlive restarts) never trigger mail.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for ServerWatcher: crash, removal, error-line batching, cancel, resume."""

from __future__ import annotations

import time
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

    class Scripted(ServerWatcher):
        backoff_schedule = [(3.0, 0.01)]
        lister = staticmethod(lambda: take(app_queue))
        log_reader = staticmethod(lambda name, lines, contains=None: take(log_queue))
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
    monkeypatch.setattr(server_watcher.settings, "watchers_dir", tmp_path)
    monkeypatch.setattr(server_watcher.identity_context, "current_username", lambda: "alice")
    monkeypatch.setattr(server_watcher.identity_context, "current_email", lambda: "alice@x.io")
    monkeypatch.setattr(ServerWatcher, "start", lambda self: started.append((self.key, self.owner, self.email, self.state_dir)))

    server_watcher.watch_app("web")

    assert started == [("web", "alice", "alice@x.io", tmp_path)]


def test_pause_watch_cancels_first_and_restores_it_when_the_action_fails(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(server_watcher.settings, "watchers_dir", tmp_path)
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
    monkeypatch.setattr(server_watcher.settings, "watchers_dir", tmp_path)
    monkeypatch.setattr(ServerWatcher, "is_active", classmethod(lambda cls, key: True))
    monkeypatch.setattr(ServerWatcher, "cancel", classmethod(lambda cls, state_dir, key: calls.append(("cancel", key))))
    monkeypatch.setattr(server_watcher, "watch_app", lambda name: calls.append(("watch", name)))

    assert server_watcher.pause_watch("web", lambda: "stopped") == "stopped"
    assert calls == [("cancel", "web")]
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_server_watcher.py -q`
Expected: FAIL (`ModuleNotFoundError: ... server_watcher`).

- [ ] **Step 3: Implement**

`apps/mcp_server/src/capabilities/server_manager/utils/server_watcher.py`:

```python
"""Watches one Docker app for as long as it runs, and tells its owner when it goes wrong.

`JobWatcher` owns the thread, the schedule, state persistence and resume. This subclass says
what a poll is (is the app still listed and running; any new error lines in its log) and what
to do about it (one email to the owner). Everything the watcher needs to resume after a
restart travels in the persisted record's `detail`.

The watcher is started by `watch_app` after `tool_srv_startApp` / `tool_srv_restartApp` and
paused around stop/restart by `pause_watch`, so a deliberate stop is never reported as a crash.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, TypeVar

from src.capabilities.server_manager.utils import notify
from src.config import settings
from src.services import identity_context
from src.services.watcher import JobWatcher, WatcherPhase, WatcherRecord

T = TypeVar("T")

ERROR_EMAIL_COOLDOWN_S = 3600.0
TAIL_LINES = 20
LOG_SCAN_LINES = 200
MAX_PENDING = 100


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _list_apps():
    from src.capabilities.server_manager import domain  # late: domain imports this module

    return domain.list_apps()


def _read_logs(name: str, lines: int, contains: str | None = None):
    from src.capabilities.server_manager import domain

    return domain.read_app_logs(name, lines, contains)


def _line_time(line: str) -> datetime | None:
    """The leading RFC 3339 timestamp Docker puts on a log line (nanoseconds, zeros may be trimmed), or None."""
    stamp = line.split(" ", 1)[0]
    if not stamp.endswith("Z"):
        return None
    head, dot, fraction = stamp[:-1].partition(".")
    text = f"{head}.{fraction[:6].ljust(6, '0')}" if dot else head
    try:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class ServerWatcher(JobWatcher):
    # Every 30 s for the first 10 minutes, then every 5 minutes, with no time limit.
    backoff_schedule = [(600.0, 30.0), (float("inf"), 300.0)]

    # Replaceable in tests (staticmethods, so `self.lister()` passes no self).
    lister = staticmethod(_list_apps)
    log_reader = staticmethod(_read_logs)
    mailer = staticmethod(notify.send_owner_email)
    clock = staticmethod(_utcnow)

    def __init__(
        self, key: str, state_dir: Path, owner: str = "", email: str = "", started_at: str | None = None,
        since: str | None = None, pending: list[str] | None = None, last_email_at: str = "", checks: int = 0,
    ) -> None:
        super().__init__(key=key, state_dir=state_dir, started_at=started_at)
        self.owner, self.email = owner, email
        self._since = since or self.clock().isoformat()
        self._pending = list(pending or [])
        self._last_email_at = last_email_at
        self._checks = checks
        self._status = ""
        self._reason = ""
        self._email_result = ""

    # --- JobWatcher contract ---------------------------------------------

    def poll(self) -> tuple[WatcherPhase, dict[str, Any]]:
        self._checks += 1
        app = next((item for item in self.lister().apps if item.name == self.key), None)
        if app is None:
            self._status, self._reason = "removed", "removed"
            return WatcherPhase.COMPLETED, self._detail()
        self._status = app.status
        if app.status != "running":
            self._reason = "crashed"
            return WatcherPhase.COMPLETED, self._detail()
        self._collect_errors()
        self._email_pending_errors()
        return WatcherPhase.RUNNING, self._detail()

    def on_completed(self, detail: dict[str, Any]) -> None:
        if self._reason == "removed":
            subject, message = f"{self.key} was removed", "The app is no longer on this host."
        else:
            subject = f"{self.key} stopped"
            message = f"The app is {self._status}, and nobody stopped it through the server tools."
        self._email_result = self._notify(subject, message, self._tail())
        detail["email_result"] = self._email_result

    @classmethod
    def from_record(cls, record: WatcherRecord) -> "ServerWatcher":
        detail = record.detail
        return cls(
            key=record.key,
            state_dir=Path("unused"),  # resume_all points it at the real directory
            owner=str(detail.get("owner", "")),
            email=str(detail.get("email", "")),
            started_at=record.started_at,
            since=str(detail.get("since", "")) or None,
            pending=list(detail.get("pending") or []),
            last_email_at=str(detail.get("last_email_at", "")),
            checks=int(detail.get("checks", 0) or 0),
        )

    def _save_record(self, phase: WatcherPhase, detail: dict[str, Any]) -> None:
        """Every save carries the owner and held lines, so a record is always enough to resume from."""
        super()._save_record(phase, {**self._detail(), **detail})

    # --- helpers ---------------------------------------------------------------

    def _detail(self) -> dict[str, Any]:
        return {
            "app": self.key, "owner": self.owner, "email": self.email, "status": self._status,
            "reason": self._reason, "checks": self._checks, "since": self._since,
            "pending": list(self._pending), "last_email_at": self._last_email_at,
            "email_result": self._email_result,
        }

    def _collect_errors(self) -> None:
        """Keeps the error lines stamped after the last one seen; older ones are never mailed."""
        since = datetime.fromisoformat(self._since)
        newest, fresh = since, []
        for line in self.log_reader(self.key, LOG_SCAN_LINES, "error").text.splitlines():
            when = _line_time(line)
            if when is not None and when > since:
                fresh.append(line)
                newest = max(newest, when)
        self._pending = (self._pending + fresh)[-MAX_PENDING:]
        self._since = newest.isoformat()

    def _email_pending_errors(self) -> None:
        if not self._pending:
            return
        now = self.clock()
        if self._last_email_at:
            elapsed = (now - datetime.fromisoformat(self._last_email_at)).total_seconds()
            if elapsed < ERROR_EMAIL_COOLDOWN_S:
                return
        lines, self._pending = self._pending, []
        self._last_email_at = now.isoformat()
        self._email_result = self._notify(
            f"Errors in {self.key}", f"{len(lines)} new error line(s) in the log of {self.key}.", lines
        )

    def _tail(self) -> list[str]:
        try:
            return self.log_reader(self.key, TAIL_LINES, None).text.splitlines()
        except Exception:  # noqa: BLE001 - a removed app has no log; the mail still goes out
            return []

    def _notify(self, subject: str, message: str, lines: list[str]) -> str:
        # `cancel` can land while a poll is in flight, so a cancelled watcher must not email its owner.
        if self._stop_event.is_set():
            return "skipped: cancelled"
        details = f"<p>App <code>{escape(self.key)}</code>, status {escape(self._status)}.</p>"
        if lines:
            details += "<pre>" + escape("\n".join(lines)) + "</pre>"
        try:
            return self.mailer(self.owner, self.email, subject, message, details)
        except Exception as error:  # noqa: BLE001 - the mailer should not raise, but a watcher must never die on mail
            return f"failed: {type(error).__name__}: {error}"[:300]


def watch_app(name: str) -> None:
    """Starts (or replaces) the watcher for `name`, owned by the account making this request."""
    ServerWatcher(
        name, settings.watchers_dir,
        owner=identity_context.current_username(), email=identity_context.current_email(),
    ).start()


def pause_watch(name: str, action: Callable[[], T]) -> T:
    """Runs `action` (a deliberate stop or restart) with the app's watcher cancelled, so it is not reported as a crash.
    If `action` fails the app is still running, so the watcher is put back."""
    was_watched = ServerWatcher.is_active(name)
    ServerWatcher.cancel(settings.watchers_dir, name)
    try:
        return action()
    except Exception:
        if was_watched:
            watch_app(name)
        raise
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_server_watcher.py tests/test_server_watcher_notify.py tests/test_watcher.py -q`
Expected: all PASS. If `test_a_cancelled_watcher_does_not_email` fails because `run()` writes nothing, that is fine: it asserts only `mails == []`.

- [ ] **Step 5: Commit**

```bash
git add apps/mcp_server/src/capabilities/server_manager/utils/server_watcher.py apps/mcp_server/tests/test_server_watcher.py
git commit -m "feat(mcp-server): ServerWatcher, first JobWatcher child"
```

---

## Task 4: list_apps reports `watched`

**Files:**
- Modify: `apps/mcp_server/src/capabilities/server_manager/contract.py`
- Modify: `apps/mcp_server/src/capabilities/server_manager/domain.py:172-186`
- Modify: `apps/mcp_server/src/capabilities/server_manager/tool.py:90-96` (docstring only here; hooks are Task 5)
- Test: `apps/mcp_server/tests/test_server_manager_domain.py`

**Interfaces:**
- Consumes: `ServerWatcher.is_active(key) -> bool` (Task 1, inherited by Task 3's class).
- Produces: `AppInfo.watched: bool`; list report line `"{name}  {status}  {watched|-}  {image}"`.

- [ ] **Step 1: Write the failing tests**

Append to `apps/mcp_server/tests/test_server_manager_domain.py` (after the list tests section):

```python
def test_list_apps_marks_the_apps_that_have_a_watcher():
    from src.capabilities.server_manager.utils.server_watcher import ServerWatcher

    client = _fake_client([_fake_container("jellyfin"), _fake_container("plex")])

    with patch("docker.from_env", return_value=client), \
            patch.object(ServerWatcher, "is_active", classmethod(lambda cls, key: key == "jellyfin")):
        result = domain.list_apps()

    assert {app.name: app.watched for app in result.apps} == {"jellyfin": True, "plex": False}
    lines = result.message.splitlines()
    assert "watched" in lines[0] and "watched" not in lines[1]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_server_manager_domain.py -q`
Expected: FAIL (`AttributeError: 'AppInfo' object has no attribute 'watched'`).

- [ ] **Step 3: Implement**

`contract.py`, in `AppInfo` after `image`:

```python
    watched: bool = Field(
        default=False,
        description="True while a ServerWatcher is monitoring this app and will email its owner if it stops or logs errors.",
    )
```

`domain.py`: add to the imports `from src.capabilities.server_manager.utils.server_watcher import ServerWatcher` (after the `redact` import) and replace the body of `list_apps` from `apps = [...]` on:

```python
    apps = [
        AppInfo(
            name=container.name,
            status=container.status,
            image=_image_label(container),
            watched=ServerWatcher.is_active(container.name),
        )
        for container in containers
    ]

    if not apps:
        report = "No apps found on this host."
    else:
        width = max(len(app.name) for app in apps)
        report = "\n".join(
            f"{app.name:<{width}}  {app.status:<10} {'watched' if app.watched else '-':<8} {app.image}"
            for app in apps
        )
```

`tool.py`, `tool_srv_listApps` docstring becomes:

```python
    """List every Docker app on this box, running or not, with the exact
    `name` to pass to the start/stop/restart tools, its status, image and
    whether it is watched (a watcher emails its owner if the app stops,
    disappears or logs errors; one starts whenever an app is started here)."""
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_server_manager_domain.py tests/test_server_watcher.py -q`
Expected: all PASS (no import cycle: `server_watcher` imports `domain` only inside functions).

- [ ] **Step 5: Commit**

```bash
git add apps/mcp_server/src/capabilities/server_manager/contract.py apps/mcp_server/src/capabilities/server_manager/domain.py apps/mcp_server/src/capabilities/server_manager/tool.py apps/mcp_server/tests/test_server_manager_domain.py
git commit -m "feat(mcp-server): list_apps shows which apps are watched"
```

---

## Task 5: Tool hooks and startup resume

**Files:**
- Modify: `apps/mcp_server/src/capabilities/server_manager/tool.py:10-47`
- Modify: `apps/mcp_server/src/run.py:134-138`
- Create: `apps/mcp_server/src/capabilities/server_manager/README.md`
- Test: `apps/mcp_server/tests/test_server_manager_tools.py`

**Interfaces:**
- Consumes: `watch_app(name)`, `pause_watch(name, action)`, `ServerWatcher.resume_all(state_dir)`.
- Produces: `tool_srv_startApp` and `tool_srv_restartApp` start a watcher after success; `tool_srv_stopApp` and the restart action run inside `pause_watch`.

- [ ] **Step 1: Write the failing tests**

`apps/mcp_server/tests/test_server_manager_tools.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_server_manager_tools.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'watch_app'`).

- [ ] **Step 3: Implement**

`tool.py` imports, add after the `contract` import:

```python
from src.capabilities.server_manager.utils.server_watcher import pause_watch, watch_app
```

Replace the three action tools' bodies:

```python
def tool_srv_startApp(name: AppName) -> AppActionResult:
    """Start a stopped Docker app hosted on this box. If `name` matches no
    container, the error lists the names that exist; `tool_srv_listApps`
    shows them all up front. Starting an app also starts a watcher that
    emails the person who started it if the app stops, disappears or logs
    errors."""
    result = domain.start_app(name)
    watch_app(name)
    return result
```

```python
def tool_srv_stopApp(name: AppName) -> AppActionResult:
    """Stop a running Docker app hosted on this box. The app stays stopped
    until started again; the container and its data are not removed. Its
    watcher ends too, so a deliberate stop sends no email."""
    return pause_watch(name, lambda: domain.stop_app(name))
```

```python
def tool_srv_restartApp(name: AppName) -> AppActionResult:
    """Restart a Docker app hosted on this box - stop, then start. Works
    whether the app is running or already stopped. The app is watched again
    afterwards (see `tool_srv_startApp`)."""
    result = pause_watch(name, lambda: domain.restart_app(name))
    watch_app(name)
    return result
```

Also change the module docstring's first line to `"""MCP tool wrappers for the server_manager capability - thin on purpose.` followed by `The start, stop and restart tools also manage the app's ServerWatcher.` then `No config: call the domain function, return its result."""`.

`run.py`: leave the existing `watch` block and add directly after it (it is removed in Task 6):

```python
        # Restart the app watchers that were running when the server last stopped.
        if "server" in capability_registry.names() and capability_registry.is_enabled("server"):
            from src.capabilities.server_manager.utils.server_watcher import ServerWatcher

            ServerWatcher.resume_all(settings.watchers_dir)
```

`apps/mcp_server/src/capabilities/server_manager/README.md` (new):

```markdown
# capabilities/server_manager/

Start, stop, restart and list the Docker apps on this host; read their logs. Chat id `server`, label "Server Manager".

## App watcher

Starting an app (`tool_srv_startApp`, `tool_srv_restartApp`) starts a `ServerWatcher` (`utils/server_watcher.py`, a
`JobWatcher` child). It polls every 30 seconds for 10 minutes, then every 5 minutes, with no time limit:

- App missing from `tool_srv_listApps` data (removed) or listed but not `running` (crashed): one email with the last
  20 log lines, then the watcher ends. Restarting the app starts a new one.
- New log lines containing "error" while running: one email with all new lines, at most one per app per hour; lines
  found during the cool-down go out in the next email.

`tool_srv_stopApp` ends the watcher first, so a deliberate stop sends no email. `tool_srv_listApps` shows which apps
are watched. Mail goes to the address of whoever started the app, through the Email capability (`notification`
template); it needs Email online and configured. The outcome is stored in the watcher's `detail["email_result"]`.

State lives under `MCP_WATCHERS_DIR` (default `.data/watchers/ServerWatcher/instances/`). Watchers are resumed when
the server starts, only while this capability is enabled.
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest tests/test_server_manager_tools.py tests/test_server_manager_domain.py tests/test_server_watcher.py tests/test_tool_display_labels.py tests/test_tool_keywords.py -q`
Expected: all PASS.

If `test_start_app_starts_the_app_then_its_watcher` fails with `TypeError: 'coroutine'...` or the tool is not directly awaitable, the `@command`/`@mcp.tool` decorators wrap it: call `tool.tool_srv_startApp.fn` or the underlying function the other tests in `tests/test_tool_display_labels.py` use, and adapt all four tests the same way.

- [ ] **Step 5: Run the whole mcp_server suite**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/mcp_server/src/capabilities/server_manager/tool.py apps/mcp_server/src/run.py apps/mcp_server/src/capabilities/server_manager/README.md apps/mcp_server/tests/test_server_manager_tools.py
git commit -m "feat(mcp-server): start, pause and resume ServerWatcher with the app tools"
```

- [ ] **Step 7: Manual check (needs Docker)**

Start the server, run `/server start <app>`, then `/server list`: the app shows `watched`. Run `docker stop <app>` outside the tools and wait up to 30 s: one email arrives and the app drops back to `-`. Restart the MCP server while an app is watched: after startup `/server list` shows it watched again.

---

## Task 6: Remove the `watchers` capability from mcp_server

**Files:**
- Delete: `apps/mcp_server/src/capabilities/watchers/` (whole folder)
- Delete: `apps/mcp_server/tests/test_watch_checks.py`, `test_watch_domain.py`, `test_watch_notify.py`, `test_watch_spec.py`, `test_watch_tool.py`, `test_user_watcher.py`
- Modify: `apps/mcp_server/src/run.py:134-139` (remove the old `watch` block, keep the `server` block)
- Modify: `apps/mcp_server/configs/config_capabilities.json.example:29` (remove the `"watch"` entry)
- Modify: `apps/mcp_server/src/config.py:77-79` (comment: state for all job watchers)
- Modify: `apps/mcp_server/.env.example:74-76` (heading `# ---- Job watchers (optional) ----`; keep `MCP_WATCHERS_DIR`)
- Modify: docs naming the capability: `apps/mcp_server/README.md` (lines ~11, ~120), `apps/mcp_server/src/capabilities/README.md`, `apps/mcp_server/src/capabilities/email/README.md`, `apps/mcp_server/src/services/email.py` (comment)

**Interfaces:**
- Keep: `services/watcher.py` (`JobWatcher`), `services/watcher_recipients.py` (used by `email/domain.py`), `tests/test_watcher.py`, `tests/test_watcher_recipients.py`.
- Leave alone: `tests/test_capability_routes.py:164,166` and `tests/test_app_config.py:866-873` use `"watch"` only as an arbitrary capability id in temp configs.

- [ ] **Step 1: Delete files**

```bash
git rm -r apps/mcp_server/src/capabilities/watchers
git rm apps/mcp_server/tests/test_watch_checks.py apps/mcp_server/tests/test_watch_domain.py apps/mcp_server/tests/test_watch_notify.py apps/mcp_server/tests/test_watch_spec.py apps/mcp_server/tests/test_watch_tool.py apps/mcp_server/tests/test_user_watcher.py
```

Also delete leftover `apps/mcp_server/src/capabilities/watchers/` cache folders if `git rm` leaves untracked `__pycache__` directories.

- [ ] **Step 2: Edit run.py, config example, config.py, .env.example, docs**

Remove the `if "watch" in capability_registry.names() ...: UserWatcher.resume_all(...)` block in `run.py` and the `"watch": {...}` object in `config_capabilities.json.example` (keep the JSON valid: check commas). Reword the other mentions as listed above so none describes a user-facing watch capability. In `capabilities/README.md` and the `mcp-capability-scaffold` skill (Task 9), "capability with watchers" still means `JobWatcher`.

- [ ] **Step 3: Check nothing still imports the removed code**

Run: `cd apps/mcp_server && grep -rnE "capabilities\.watchers|capabilities/watchers|tool_watch_|UserWatcher|WatchSpec" src tests configs README.md`
Expected: no output. Fix every hit (also check `tests/test_tool_keywords.py` and `tests/test_tool_display_labels.py`, which mentioned `watch`).

- [ ] **Step 4: Run the suite**

Run: `cd apps/mcp_server && .venv_mcp/Scripts/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A apps/mcp_server
git commit -m "refactor(mcp-server): remove the watchers capability"
```

---

## Task 7: Remove the Watchers route from ember_api

**Files (inspect each hit; "watchers" in `services/turns.py`, `test_traffic*.py`, `test_approvals.py` and `test_agent_events.py` may mean browsers watching a chat turn over SSE, which stays):**
- Delete: `apps/Ember/ember_api/src/routes/watchers.py`, `apps/Ember/ember_api/tests/test_watchers.py`
- Modify: `apps/Ember/ember_api/src/app.py` (router include), `src/services/permissions.py` (watchers permission), `src/services/server_tools.py` (watchers methods and the tool-name constant), `tests/conftest.py`, `README.md`
- Check: `src/services/turns.py`, `tests/test_approvals.py`, `tests/test_traffic.py`, `tests/test_traffic_analytics.py`, `tests/test_user_extension_turn.py`, `tests/test_agent_events.py`

- [ ] **Step 1: List every real reference**

Run: `cd apps/Ember/ember_api && grep -rnE "tool_watch|listWatchers|routes.watchers|watchers_router|WATCHERS|view_watchers|/api/watchers" src tests README.md`
Expected: a list limited to the files above. Note which hits are the Watchers feature.

- [ ] **Step 2: Remove the feature code and tests**

Delete the two files, remove the router include in `app.py`, the permission in `permissions.py` (check how permissions are stored: an existing role that holds the removed permission must still load, so keep the loader tolerant of unknown permission names; add a test if it is not), and the `server_tools.py` code that calls `tool_watch_listWatchers`. Update `conftest.py` and the other test files so they no longer reference the feature.

- [ ] **Step 3: Verify**

Run: `cd apps/Ember/ember_api && .venv_ember_api/Scripts/python -m pytest -q` and the same grep as Step 1.
Expected: tests PASS; grep shows only unrelated SSE-"watchers" prose, if any.

- [ ] **Step 4: Commit**

```bash
git add -A apps/Ember/ember_api
git commit -m "refactor(ember-api): remove the watchers route and permission"
```

---

## Task 8: Remove the Watchers page from ember_web (approval-gated)

**Before every sub-step below, tell the user what you will change and wait for a yes.**

**Files:**
- Delete: `apps/Ember/ember_web/src/views/WatchersView.vue`, `WatchersView.test.ts`, `src/components/watchers/` (4 files + test), `src/api/WatchersClient.ts`, `src/utils/watchers.ts`, `src/utils/watchers.test.ts`
- Modify: `src/router/index.ts`, `src/router/pages.ts`, `src/router/index.test.ts` (route and nav entry), `src/views/OverviewView.vue` and `OverviewView.test.ts` (watcher tiles), `src/components/infoPage.css` (styles used only by the page), `src/radiusScale.test.ts` (allow-list entry, if it names a watchers file), `README.md`
- Check: `src/utils/welcome.ts` and `welcome.test.ts`, `src/stores/chat.ts`, `src/composables/useChatRoute.ts`, `src/style.css` (hits may be unrelated "watching a turn" prose)

- [ ] **Step 1:** Run `cd apps/Ember/ember_web && grep -rnE "atcher" src README.md` and show the user the grouped list. Ask approval for the delete-and-edit plan.
- [ ] **Step 2:** After approval, delete the files and edit the modified files.
- [ ] **Step 3:** Run `npx vitest run` and `npx vue-tsc --noEmit` (or the scripts in `package.json`). Expected: PASS.
- [ ] **Step 4: Commit**

```bash
git add -A apps/Ember/ember_web
git commit -m "refactor(ember-web): remove the Watchers page"
```

---

## Task 9: ember_admin, docs, skills, leftovers

**Files:**
- Modify: `apps/Ember/ember_admin/src/components/admin/RoleEditor.vue` (watchers permission row), `apps/Ember/ember_admin/src/components/infoPage.css`, `apps/Ember/ember_admin/README.md`
- Modify: `_TODO.md:82,87` (Scheduler test line and Email line), `.agents/skills/mcp-capability-scaffold/SKILL.md` (13 hits; "Background job watchers" section now cites `ServerWatcher` as the worked example and states that a watcher is started by the capability's tool layer), `.agents/skills/ember-feature-scaffold/SKILL.md:170`
- Then run `python sync_skills.py` (copies to `.claude/skills/`; never edit that folder)
- Report only: `apps/ai_agent/agents/scheduler.json` stays; its only tools were `tool_watch_*`, so it now has none. Tell the user and ask what to do with it.

- [ ] **Step 1:** `grep -rnE "atcher" apps/Ember/ember_admin/src apps/Ember/ember_admin/README.md`, remove the permission row and styles; run `cd apps/Ember/ember_admin && npx vitest run` if tests exist.
- [ ] **Step 2:** Edit `_TODO.md` and the two skills; run `python sync_skills.py` then `python sync_skills.py --check` (expected: no drift).
- [ ] **Step 3:** Final sweep: `grep -rnE "tool_watch_|capabilities/watchers|/watch " --include=*.py --include=*.vue --include=*.ts --include=*.json --include=*.md . --exclude-dir=node_modules --exclude-dir=.venv_* --exclude-dir=.worktrees --exclude-dir=docs`
  Expected: only `apps/ai_agent/agents/scheduler.json` (and its `.data` copies).
- [ ] **Step 4: Commit**

```bash
git add -A apps/Ember/ember_admin _TODO.md .agents .claude/skills
git commit -m "docs: watchers capability removed, ServerWatcher is the JobWatcher example"
```

- [ ] **Step 5:** Offer to run project-sync for `Brain/Projects/MCPServer.md` and the component notes (`mcp_server`, `ember_web`, `ember_api`).

---

## Self-review

- **Spec coverage:** start/stop hooks (Task 5), polling and both email kinds (Task 3), cool-down and batching (Task 3), resume (Tasks 1, 3, 5), `watched` flag (Task 4), base-class changes (Task 1), removal (Tasks 6-9), open-ended schedule (Task 3 uses `float("inf")`, noted under Global Constraints).
- **Placeholders:** none in code tasks. Tasks 7-9 describe deletions with exact grep commands because the exact lines depend on inspection; each ends in a verifying command.
- **Types:** `send_owner_email(owner, email, subject, message, details_html)` matches the `mailer(self.owner, self.email, subject, message, details)` call; `watch_app(name)` and `pause_watch(name, action)` match their use in `tool.py` and tests.
