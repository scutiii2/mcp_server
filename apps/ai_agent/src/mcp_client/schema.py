"""Tool-schema clean-up applied to every upstream tool before an LLM sees it.

Pydantic writes a nested model as `{"$ref": "#/$defs/Name"}` plus a `$defs`
block. Anthropic and OpenAI accept that; several OpenAI-compatible gateways
(Together, Groq, Ollama, ...) ignore or reject it, so the model never learns
the nested shape. Inlining the definitions gives every backend the same
plain schema.
"""

from __future__ import annotations

import copy
from typing import Any

_LOCAL_PREFIX = "#/$defs/"


class _Unresolvable(Exception):
    """A $ref that cannot be inlined: not local, undefined, or recursive."""


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """A copy of `schema` with every local `$ref` replaced by its `$defs`
    entry and the `$defs` block dropped. Keywords next to a `$ref` (such as
    `description`) win over the definition's. A schema that cannot be fully
    inlined (recursive, or a `$ref` outside `$defs`) comes back unchanged,
    since a half-inlined one would be worse than the original."""
    defs = schema.get("$defs", {})
    try:
        inlined = _inline(schema, defs, ())
    except _Unresolvable:
        return copy.deepcopy(schema)
    inlined.pop("$defs", None)
    return inlined


def _inline(node: Any, defs: dict[str, Any], active: tuple[str, ...]) -> Any:
    if isinstance(node, list):
        return [_inline(item, defs, active) for item in node]
    if not isinstance(node, dict):
        return node

    ref = node.get("$ref")
    if ref is None:
        return {key: _inline(value, defs, active) for key, value in node.items()}

    name = ref.removeprefix(_LOCAL_PREFIX) if isinstance(ref, str) and ref.startswith(_LOCAL_PREFIX) else None
    if name is None or name not in defs or name in active:
        raise _Unresolvable(ref)
    resolved = _inline(defs[name], defs, (*active, name))
    beside = {key: _inline(value, defs, active) for key, value in node.items() if key != "$ref"}
    return {**resolved, **beside}
