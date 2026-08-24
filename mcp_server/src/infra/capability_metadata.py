"""Per-capability display metadata: TITLE and COMMAND_ID.

Each capabilities/<name>/__init__.py MAY define two optional
module-level constants::

    TITLE = "Host Health"    # shown on chat_app's Capabilities page
    COMMAND_ID = "host"      # the "/<id> <tool> ..." prefix chat_app's
                              # slash commands parse - meant to be
                              # shorter than the real capability id (the
                              # folder name, e.g. "host_health") when
                              # typing it often is worth the brevity

Both are optional and fall back to the real id itself when a package
defines neither - a capability with no TITLE/COMMAND_ID still works
exactly as it did before this module existed, just with a less catchy
display name. Read fresh on every call rather than cached: neither is
ever on a hot path (GET /capabilities and one startup validation are
the only callers), so there's nothing to gain from caching and one less
thing to go stale.

Kept out of infra/capability_registry.py on purpose: that module tracks
toggle STATE (what's enabled, which tools/templates a capability owns);
this one is static DISPLAY metadata. Different concerns, same split as
chat_app's tool_titles.py vs tool_capabilities.py.

The real capability id (what config_capabilities.json keys on, what
commands.py's @command decorator infers from the module path, what
capability_registry.capturing() is called with in run.py) must stay the
capabilities/<name>/ folder name everywhere - COMMAND_ID is a display
alias for chat_app only, never a substitute for the real id.
"""

from __future__ import annotations

import importlib


def _package(name: str):
    # None (not a raised ImportError) for a name with no matching
    # capabilities/<name>/ package - real capabilities always have one,
    # but a capability registered directly against capability_registry
    # (as this module's own tests do, and conceivably a future capability
    # that isn't file-backed) shouldn't crash a GET /capabilities call
    # just because it has no folder to look TITLE/COMMAND_ID up from.
    try:
        return importlib.import_module(f"src.capabilities.{name}")
    except ModuleNotFoundError:
        return None


def title_for(name: str) -> str:
    return getattr(_package(name), "TITLE", name)


def command_id_for(name: str) -> str:
    return getattr(_package(name), "COMMAND_ID", name)


def validate_command_ids(names: list[str]) -> None:
    """Raise if two capabilities resolve to the same COMMAND_ID.

    Each capability owns its "/<command_id> <tool> ..." prefix in
    chat_app uniquely - two capabilities sharing one would mean whichever
    got parsed first silently shadows the other's commands, a failure
    mode nobody would notice until a command that should exist reports
    "unknown". Called once at startup (see run.py), after every
    capability has been imported and captured - not from
    command_id_for() itself, since a single lookup has no way to know
    about its siblings.
    """
    owner_by_command_id: dict[str, str] = {}
    for name in names:
        command_id = command_id_for(name)
        if command_id in owner_by_command_id:
            raise ValueError(
                f"Capabilities {owner_by_command_id[command_id]!r} and {name!r} both resolve to "
                f"COMMAND_ID {command_id!r} - give one of their __init__.py a distinct COMMAND_ID."
            )
        owner_by_command_id[command_id] = name
