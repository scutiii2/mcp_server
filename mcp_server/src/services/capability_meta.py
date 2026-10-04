"""Single per-capability identity: a short id (used both for the chat
"/<id> ..." slash alias and mcp_server's own capability_registry/toggle
name) and a human-readable label - declared once, in each capability's
own ``__init__.py``, instead of being repeated at every place that needs
it.

Before this existed, the same string showed up in three places per
capability: ``run.py``'s ``capability_registry.capturing(mcp, "server")``,
every single ``@command(..., capability="server")`` call in that
capability's ``tool.py`` (eight of them, for ``server_manager``
alone), and chat_app's hand-maintained ``tool_capabilities.py`` - three
copies of one fact, one of which (chat_app's) isn't even in this
codebase. Registering it here once means:

- ``commands.py``'s ``@command`` decorator infers the id from this
  registry instead of requiring an explicit ``capability=`` override on
  every call (see ``commands._infer_capability``).
- ``run.py`` passes the id/label straight into
  ``capability_registry.capturing()``.
- ``capability_routes.py`` exposes the label (and, via
  ``capability_registry.tool_names()``/``resource_names()``, which
  tools/resources belong to it) over ``GET /capabilities``, so chat_app
  never needs its own copy of either - see chat_app's
  ``services/tool_capabilities.py``.

Keyed by folder name (``server_manager``), not by the short id
(``server``): the lookup direction actually needed is "given the folder
an ``@command``-decorated function lives in, what's its id/label",
which is exactly what ``commands.py``'s module-path parsing already had
before this module existed - it just had nowhere to look the folder up.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.utils.catalog import catalog


@catalog
@dataclass(frozen=True)
class CapabilityMeta:
    id: str
    label: str


_BY_FOLDER: dict[str, CapabilityMeta] = {}


def register(folder: str, id: str, label: str) -> CapabilityMeta:  # noqa: A002 - `id` reads best as-is here
    """Call once from ``capabilities/<folder>/__init__.py``. Raises if
    `folder` was already registered - the same "catch a copy-paste
    mistake immediately" reasoning as ``commands.py``'s duplicate-key
    check on ``_COMMANDS``."""
    if folder in _BY_FOLDER:
        raise ValueError(f"Capability folder {folder!r} is already registered")
    meta = CapabilityMeta(id=id, label=label)
    _BY_FOLDER[folder] = meta
    return meta


def for_folder(folder: str) -> CapabilityMeta | None:
    """None for a folder that never called ``register()`` - callers fall
    back to the folder name itself (see
    ``commands.py``'s ``_infer_capability``), the same "don't silently
    break, just degrade" reasoning chat_app's old ``tool_capabilities.py``
    used for a tool with no map entry."""
    return _BY_FOLDER.get(folder)


def folder_for_id(id: str) -> str | None:  # noqa: A002 - matches register()'s `id` param name
    """Reverse of ``for_folder()``: which capability folder registered
    this chat-facing id (e.g. ``"server"`` -> ``"server_manager"``).
    None if no capability has registered it. Used by
    ``capability_help.py`` to find a capability's ``help.json`` on disk
    from the id a ``/<capability> help`` command names."""
    for folder, meta in _BY_FOLDER.items():
        if meta.id == id:
            return folder
    return None
