"""What one watcher watches, validated, plus the dispatch that runs its check.

A `WatchSpec` is all strings so it survives a round trip through a watcher's
persisted `detail` dict unchanged; that round trip is how a watcher is
rebuilt after a restart.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from src.capabilities.watchers.utils import checks
from src.capabilities.watchers.utils.checks import CheckResult

KINDS = ("url", "app", "tcp")
EXPECTS = ("up", "down")
MAX_CONTAINS = 100
MAX_LABEL = 60


@dataclass(frozen=True)
class WatchSpec:
    kind: str
    target: str
    expect: str
    contains: str
    label: str
    owner: str
    email: str

    def to_detail(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_detail(cls, detail: dict[str, Any]) -> "WatchSpec":
        return cls(**{name: str(detail.get(name, "")) for name in cls.__dataclass_fields__})

    def title(self) -> str:
        return self.label or self.target

    def condition_text(self) -> str:
        """The condition in words, for summaries and emails."""
        up = self.expect == "up"
        if self.kind == "url":
            text = f"{self.target} to be {'reachable' if up else 'unreachable'}"
            return text + (f" and contain {self.contains!r}" if self.contains and up else "")
        if self.kind == "app":
            return f"app {self.target} to be {'running' if up else 'not running'}"
        return f"{self.target} to be {'open' if up else 'closed'}"


def build_spec(kind: str, target: str, expect: str, contains: str, label: str, owner: str, email: str) -> WatchSpec:
    """A validated, normalised spec, or a ValueError naming what to fix."""
    kind, expect = kind.strip().lower(), (expect or "up").strip().lower()
    target, contains, label = target.strip(), (contains or "").strip(), (label or "").strip()
    for name, value in (("target", target), ("contains", contains), ("label", label)):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(f"{name} must not contain control characters.")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of: {', '.join(KINDS)}.")
    if expect not in EXPECTS:
        raise ValueError(f"expect must be one of: {', '.join(EXPECTS)}.")
    if contains and (kind != "url" or expect != "up"):
        raise ValueError("contains only works with kind url and expect up.")
    if len(contains) > MAX_CONTAINS:
        raise ValueError(f"contains must be at most {MAX_CONTAINS} characters.")
    if len(label) > MAX_LABEL:
        raise ValueError(f"label must be at most {MAX_LABEL} characters.")
    if kind == "url":
        target = checks.validate_url(target)
    elif kind == "tcp":
        checks.parse_tcp_target(target)
    elif not checks.valid_app_name(target):
        raise ValueError("The app name may only use letters, digits, dots, hyphens and underscores.")
    return WatchSpec(kind, target, expect, contains, label, owner, email)


def run_check(spec: WatchSpec, *, list_apps: Callable[[], Any] | None = None) -> CheckResult:
    """Runs the one check this spec names."""
    if spec.kind == "url":
        return checks.check_url(spec.target, spec.contains)
    if spec.kind == "tcp":
        host, port = checks.parse_tcp_target(spec.target)
        return checks.check_tcp(host, port)
    if list_apps is None:
        from src.capabilities.server_manager.domain import list_apps as default_list_apps

        list_apps = default_list_apps
    return checks.check_app(spec.target, list_apps)
