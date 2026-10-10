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
