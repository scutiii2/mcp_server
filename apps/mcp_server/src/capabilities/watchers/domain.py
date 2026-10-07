"""Create, list and cancel user-defined watchers.

Functions take the state directory and the caller's name and address instead
of reaching for globals, so tests (and the tool wrappers) decide where state
lives and who is asking. Every watcher belongs to its creator: list and cancel
only ever see the caller's own, and a key that is not the caller's gets the
same "No such watcher." as one that does not exist.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.capabilities.watchers.contract import CancelResult, CreateResult, WatcherListResult, WatcherRow
from src.capabilities.watchers.utils.spec import WatchSpec, build_spec
from src.capabilities.watchers.utils.user_watcher import UserWatcher
from src.services import watcher_recipients
from src.services.watcher import WatcherPhase, WatcherRecord

MAX_PER_OWNER = 5
MAX_TOTAL = 50
MAX_FINISHED = 20
MAX_APPS_LISTED = 20

_KEY = re.compile(r"w-[0-9a-f]{8}")


def create_watcher(
    state_dir: Path,
    owner: str,
    email: str,
    kind: str,
    target: str,
    expect: str = "up",
    contains: str = "",
    label: str = "",
    *,
    factory: type[UserWatcher] = UserWatcher,
    list_apps: Callable[[], Any] | None = None,
) -> CreateResult:
    _require_owner(owner)
    spec = build_spec(kind, target, expect, contains, label, owner, email.strip())
    if spec.kind == "app":
        _require_known_app(spec, list_apps)
    records = _records(state_dir, factory)
    running = [r for r in records if r.phase == WatcherPhase.RUNNING]
    if sum(1 for r in running if r.detail.get("owner") == owner) >= MAX_PER_OWNER:
        raise ValueError(f"You already have {MAX_PER_OWNER} running watchers. Cancel one first, or wait for one to finish.")
    if len(running) >= MAX_TOTAL:
        raise ValueError("The watcher service is busy. Try again later.")
    _prune_finished(state_dir, owner, records, factory)

    key = f"w-{secrets.token_hex(4)}"
    if spec.email:
        watcher_recipients.set_recipients(state_dir, factory.__name__, key, [spec.email])
    factory(key=key, state_dir=state_dir, spec=spec).start()
    return CreateResult(key=key, message=_summary(spec, key))


def list_watchers(state_dir: Path, owner: str, *, factory: type[UserWatcher] = UserWatcher) -> WatcherListResult:
    _require_owner(owner)
    mine = sorted(
        (r for r in _records(state_dir, factory) if r.detail.get("owner") == owner),
        key=lambda r: r.started_at,
        reverse=True,
    )
    rows = [
        WatcherRow(
            key=r.key,
            phase=r.phase.value,
            started_at=r.started_at,
            last_polled_at=r.last_polled_at,
            detail=r.detail,
            recipients=watcher_recipients.get_recipients(state_dir, factory.__name__, r.key),
        )
        for r in mine
    ]
    noun = "watcher" if len(rows) == 1 else "watchers"
    return WatcherListResult(watchers=rows, message=f"{len(rows)} {noun}." if rows else "You have no watchers.")


def cancel_watcher(state_dir: Path, owner: str, key: str, *, factory: type[UserWatcher] = UserWatcher) -> CancelResult:
    _require_owner(owner)
    key = key.strip()
    # The key is checked against the strict pattern and then against the records on disk;
    # it is never used to build a path unless it is one of this owner's own records.
    record = next(
        (r for r in _records(state_dir, factory) if r.key == key and r.detail.get("owner") == owner),
        None,
    ) if _KEY.fullmatch(key) else None
    if record is None:
        raise ValueError("No such watcher.")
    factory.cancel(state_dir, record.key)
    watcher_recipients.set_recipients(state_dir, factory.__name__, record.key, [])
    return CancelResult(key=record.key, message=f"Cancelled watcher {record.key}.")


def _require_owner(owner: str) -> None:
    if not owner:
        raise ValueError("The caller is not identified, so watchers cannot be used.")


def _records(state_dir: Path, factory: type[UserWatcher]) -> list[WatcherRecord]:
    folder = state_dir / factory.__name__ / "instances"
    if not folder.is_dir():
        return []
    records: list[WatcherRecord] = []
    for path in sorted(folder.glob("*.json")):
        try:
            records.append(WatcherRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 - one corrupt record must not break the others
            continue
    return records


def _prune_finished(state_dir: Path, owner: str, records: list[WatcherRecord], factory: type[UserWatcher]) -> None:
    """Keeps an owner's newest MAX_FINISHED finished records; deletes the rest and their recipients."""
    finished = sorted(
        (r for r in records if r.phase != WatcherPhase.RUNNING and r.detail.get("owner") == owner),
        key=lambda r: r.last_polled_at,
        reverse=True,
    )
    for old in finished[MAX_FINISHED:]:
        factory.cancel(state_dir, old.key)
        watcher_recipients.set_recipients(state_dir, factory.__name__, old.key, [])


def _require_known_app(spec: WatchSpec, list_apps: Callable[[], Any] | None) -> None:
    if list_apps is None:
        from src.capabilities.server_manager.domain import list_apps as default_list_apps

        list_apps = default_list_apps
    try:
        names = [app.name for app in list_apps().apps]
    except Exception as error:  # noqa: BLE001 - Docker missing or unreachable is the one expected cause
        raise ValueError(f"Docker is not available on this host, so app watchers cannot be created: {error}") from error
    if spec.target not in names:
        listed = ", ".join(repr(name) for name in names[:MAX_APPS_LISTED]) or "none"
        raise ValueError(f"No app named {spec.target!r}. Known apps: {listed}.")


def _summary(spec: WatchSpec, key: str) -> str:
    mail = (
        f"One email goes to {spec.email} when it happens."
        if spec.email
        else "No email address is known for you, so no email will be sent; the result shows on the Watchers page."
    )
    return (
        f"Watching for {spec.condition_text()}. Watcher {key}. "
        f"It checks every 30 seconds for 10 minutes, then every 5 minutes, and gives up after 24 hours. {mail}"
    )
