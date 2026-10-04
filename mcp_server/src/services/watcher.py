"""Shared background-polling watcher base class.

Owns threading, backoff-schedule polling, state persistence, and
startup resume. What "poll" and "job finished" mean is entirely
subclass-owned - one subclass per capability.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class WatcherPhase(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class WatcherRecord(BaseModel):
    key: str
    phase: WatcherPhase
    started_at: str
    last_polled_at: str
    detail: dict[str, Any] = Field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobWatcher(ABC):
    """One polling loop for one background job. Subclass per capability."""

    backoff_schedule: list[tuple[float, float]] = [(24 * 3600, 3600)]

    _active: dict[str, dict[str, threading.Event]] = {}
    _active_lock = threading.Lock()

    def __init__(self, key: str, state_dir: Path, started_at: str | None = None) -> None:
        self.key = key
        self.state_dir = state_dir
        self._started_at = started_at or _now_iso()
        self._stop_event = threading.Event()

    # --- subclass contract --------------------------------------------

    @abstractmethod
    def poll(self) -> tuple[WatcherPhase, dict[str, Any]]:
        """Call this job's status check. Return the new phase and a detail
        dict to persist. Raise on transient error - run() catches it,
        logs, and retries on the next tick rather than crashing the
        thread."""

    def on_completed(self, detail: dict[str, Any]) -> None:
        """Called once, when phase transitions into COMPLETED. Default:
        no-op. May mutate `detail` in place to add fields (e.g. a
        downloaded file's path) before it's persisted."""

    def on_state_change(
        self, old: WatcherPhase, new: WatcherPhase, detail: dict[str, Any]
    ) -> None:
        """Called after every poll where phase changed. Default: no-op.
        Reserved for a future notification hook."""

    @classmethod
    @abstractmethod
    def from_record(cls, record: WatcherRecord) -> "JobWatcher":
        """Rehydrate a subclass instance from a persisted WatcherRecord,
        enough to resume polling after a server restart."""

    # --- generic loop ---------------------------------------------------

    def _state_path(self) -> Path:
        safe_key = self.key.replace("/", "_").replace("\\", "_").replace(":", "_")
        return self.state_dir / type(self).__name__ / "instances" / f"{safe_key}.json"

    def _save_record(self, phase: WatcherPhase, detail: dict[str, Any]) -> None:
        record = WatcherRecord(
            key=self.key, phase=phase, started_at=self._started_at,
            last_polled_at=_now_iso(), detail=detail,
        )
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")

    def _interval_for_elapsed(self, elapsed: float) -> float | None:
        """The poll interval for how long the watcher has been running, or
        None once elapsed exceeds the schedule's last cutoff (timed out)."""
        for cutoff, interval in self.backoff_schedule:
            if elapsed < cutoff:
                return interval
        return None

    def run(self) -> None:
        """Thread target: backoff loop, state persistence, terminal
        handling. Safe to call directly (synchronously) in tests when
        `poll()` is finite/deterministic."""
        start = datetime.fromisoformat(self._started_at)
        phase = WatcherPhase.RUNNING
        detail: dict[str, Any] = {}
        self._save_record(phase, detail)

        while not self._stop_event.is_set():
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            interval = self._interval_for_elapsed(elapsed)
            if interval is None:
                old_phase, phase = phase, WatcherPhase.TIMED_OUT
                self._save_record(phase, detail)
                self.on_state_change(old_phase, phase, detail)
                self._deregister()
                return

            try:
                new_phase, detail = self.poll()
            except Exception as exc:  # noqa: BLE001 - one bad poll must not kill the thread
                print(f"[{type(self).__name__}] {self.key}: error during poll - {exc}")
                self._stop_event.wait(interval)
                continue

            old_phase, phase = phase, new_phase
            self._save_record(phase, detail)
            if phase != old_phase:
                self.on_state_change(old_phase, phase, detail)

            if phase == WatcherPhase.COMPLETED:
                try:
                    self.on_completed(detail)
                except Exception as exc:  # noqa: BLE001
                    phase = WatcherPhase.FAILED
                    detail = {**detail, "message": f"on_completed failed: {exc}"}
                self._save_record(phase, detail)
                self._deregister()
                return

            if phase == WatcherPhase.FAILED:
                self._deregister()
                return

            self._stop_event.wait(interval)

    def start(self) -> None:
        """Spawn run() as a daemon thread, replacing any watcher already
        registered under this key."""
        registry = type(self)._active.setdefault(type(self).__name__, {})
        with type(self)._active_lock:
            existing = registry.get(self.key)
            if existing is not None:
                existing.set()
            registry[self.key] = self._stop_event
        thread = threading.Thread(
            target=self.run, daemon=True, name=f"{type(self).__name__}_{self.key}"
        )
        thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._deregister()

    def _deregister(self) -> None:
        registry = type(self)._active.get(type(self).__name__)
        if registry is not None:
            with type(self)._active_lock:
                registry.pop(self.key, None)

    @classmethod
    def resume_all(cls, state_dir: Path) -> list["JobWatcher"]:
        """Reload every persisted RUNNING record for this subclass and
        restart it. A record that fails to read/reconstruct is logged
        and skipped, not fatal - matches the existing
        degrade-to-empty behavior for a corrupt state file."""
        started: list[JobWatcher] = []
        watcher_dir = state_dir / cls.__name__ / "instances"
        if not watcher_dir.is_dir():
            return started
        for path in sorted(watcher_dir.glob("*.json")):
            try:
                record = WatcherRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001 - a corrupt file must not block startup
                print(f"[{cls.__name__}] could not read {path}: {exc}")
                continue
            if record.phase != WatcherPhase.RUNNING:
                continue
            try:
                watcher = cls.from_record(record)
                watcher.start()
                started.append(watcher)
            except Exception as exc:  # noqa: BLE001
                print(f"[{cls.__name__}] could not resume {record.key}: {exc}")
        return started
