"""Tool-shaped view of host health.

The gathering and parsing live in ``resources/host_health/domain.py`` and
are imported, never copied. This module exists for the things that are
genuinely different when a *model* is the caller rather than a client
reading a URI:

- **A wrong name has to be recoverable.** A resource read is driven by a
  person who picked the URI, so "unknown host" is enough. A model guesses
  names, and the useful answer names the hosts that do exist - which is
  why ``known_host_names`` reads them without resolving any ``${VAR}``,
  so a host whose secret is unset still appears in the list instead of
  vanishing from the one message that was supposed to help.
- **The result is structured.** A resource's content is its text; a tool
  answers something that may need to compare figures, so the report and
  the parsed values travel together.

The direction of the dependency is deliberate: capability imports
resource. The resource came first and owns the logic; a capability that
wraps one should be additive, so deleting the wrapper leaves the resource
untouched.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.capabilities.host_health.contract import HostHealthResult
from mcp_server.infra.app_config import load_config, load_host_config
from mcp_server.resources.host_health.domain import collect, format_report


def known_host_names(config_path: Path) -> list[str]:
    """Configured host names, without resolving any placeholders.

    Names are JSON keys, so they are readable from the unresolved
    document. Going through ``load_hosts_config`` here would fail whenever
    *any* host had an unset secret, and the one moment this is called is
    when someone already got a name wrong - failing then would replace a
    helpful message with a confusing one.
    """
    section = load_config(config_path).get("hosts")
    if not isinstance(section, dict):
        return []
    return sorted(section)


def check(config_path: Path, name: str) -> HostHealthResult:
    """Read one host's health, or raise with the names that would have worked."""
    try:
        config = load_host_config(config_path, name)
    except KeyError as error:
        known = known_host_names(config_path)
        raise KeyError(
            f"No host named {name!r} is configured. "
            f"{'Configured hosts: ' + ', '.join(known) + '.' if known else 'No hosts are configured at all.'}"
        ) from error

    health = collect(config)
    return HostHealthResult(name=name, report=format_report(health), health=health)
