"""The one watcher class behind every user-defined watch.

`JobWatcher` owns the thread, the backoff schedule, state persistence and
resume. This subclass only says what a poll is (run the spec's check) and what
to do at the end (email the owner). The spec travels in the persisted record's
`detail`, which is what lets `resume_all` rebuild a watcher after a restart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.capabilities.watchers.utils import notify, spec as spec_module
from src.capabilities.watchers.utils.spec import WatchSpec
from src.services.watcher import JobWatcher, WatcherPhase, WatcherRecord


class UserWatcher(JobWatcher):
    # Every 30 s for the first 10 minutes, then every 5 minutes up to 24 hours.
    backoff_schedule = [(600.0, 30.0), (86400.0, 300.0)]

    # Replaceable in tests (staticmethods, so `self.checker(spec)` passes no self).
    checker = staticmethod(spec_module.run_check)
    notifier = staticmethod(notify.send_watcher_email)

    # Set by resume_all so rebuilt watchers save under the real state directory.
    _resume_dir: Path = Path("unused")

    def __init__(
        self, key: str, state_dir: Path, spec: WatchSpec, started_at: str | None = None, checks: int = 0
    ) -> None:
        super().__init__(key=key, state_dir=state_dir, started_at=started_at)
        self.spec = spec
        self._checks = checks

    def poll(self) -> tuple[WatcherPhase, dict[str, Any]]:
        result = self.checker(self.spec)
        self._checks += 1
        wanted_up = self.spec.expect == "up"
        matched = result.up is not None and result.up == wanted_up
        detail = {"last_check": result.detail, "checks": self._checks}
        return (WatcherPhase.COMPLETED if matched else WatcherPhase.RUNNING), detail

    def on_completed(self, detail: dict[str, Any]) -> None:
        detail["email_result"] = self._notify("met")

    def on_state_change(self, old: WatcherPhase, new: WatcherPhase, detail: dict[str, Any]) -> None:
        if new == WatcherPhase.TIMED_OUT:
            detail["email_result"] = self._notify("timed_out")
            self._save_record(new, detail)

    def _notify(self, event: str) -> str:
        # `cancel` can land while a poll is in flight; the base loop still calls the hooks,
        # so a deleted watcher must not email its owner.
        if self._stop_event.is_set():
            return "skipped: cancelled"
        try:
            return self.notifier(self.spec, self.key, event, self._checks)
        except Exception as error:  # noqa: BLE001 - the notifier should not raise, but a watcher must never die on mail
            return f"failed: {type(error).__name__}: {error}"[:300]

    def _save_record(self, phase: WatcherPhase, detail: dict[str, Any]) -> None:
        """Every save carries the spec, so a record is always enough to resume from.

        Once a watcher is cancelled (stop event set) the guard below stops its writes, so a poll
        still running when `cancel` deleted the record does not bring it back. A write that was
        already past the check when `cancel` landed can still go through (a microsecond window)."""
        if self._stop_event.is_set():
            return
        super()._save_record(phase, {**self.spec.to_detail(), **detail})

    @classmethod
    def from_record(cls, record: WatcherRecord) -> "UserWatcher":
        detail = record.detail
        return cls(
            key=record.key,
            state_dir=cls._resume_dir,
            spec=WatchSpec.from_detail(detail),
            started_at=record.started_at,
            checks=int(detail.get("checks", 0) or 0),
        )

    @classmethod
    def cancel(cls, state_dir: Path, key: str) -> None:
        """Stops the running watcher with this key, if any, and deletes its record."""
        with cls._active_lock:
            event = cls._active.get(cls.__name__, {}).pop(key, None)
        if event is not None:
            event.set()
        (state_dir / cls.__name__ / "instances" / f"{key}.json").unlink(missing_ok=True)

    @classmethod
    def resume_all(cls, state_dir: Path) -> list[JobWatcher]:
        """The base resume, with rebuilt watchers pointed at the real state directory."""
        cls._resume_dir = state_dir
        return super().resume_all(state_dir)
