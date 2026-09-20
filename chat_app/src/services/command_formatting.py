"""Formats a "/" command's raw MCP tool result for display as the chat
reply, instead of dumping the tool's raw JSON text (every built-in tool
here returns a Pydantic model, and FastMCP serializes that to indented
JSON as the tool call's text content - readable to a machine, not to
whoever just typed a command).

Deliberately generic rather than a per-tool-name map, unlike
tool_titles.py/tool_capabilities.py: those two have already gone stale
once each when a new capability was added (see git history) without
anyone remembering to add an entry. A formatter that walks whatever
JSON object comes back needs no such maintenance, and keeps working for
a tool this file has never heard of.

Every result contract in mcp_server/src/capabilities/*/contract.py
follows one of two shapes:

- flat scalar fields, a few list[dict] fields (each dict sharing the
  same keys, since they all come from one contract), and a
  human-readable ``message`` field - the common case.
- a nested ``status`` object plus a preformatted ``report`` string
  (e.g. a status-report result) - used when a tool's
  output reads better as a fixed-width block (aligned labels, a report
  title) than as prose or a bullet list.

A generic render (report or message first, then a bullet per scalar, a
table per list of dicts, a bullet list per list of scalars) reads
naturally for both shapes without knowing which tool produced the
result. See mcp_server/src/capabilities/README.md's "Output formatting"
section for the convention new capabilities should follow.
"""

from __future__ import annotations

import json

from src.utils.catalog import catalog


@catalog
def format_command_result(raw: str) -> str:
    """Best-effort Markdown formatting of `raw` - the text
    mcp_client.call_tool() returned. Anything that isn't a JSON object -
    a CommandError's "❌ ..." message, a plain-text resource read, a
    tool whose result isn't structured - passes through unchanged, so
    this never turns a working reply into something worse.
    """
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(data, dict):
        return raw

    formatted = _format_object(data)
    return formatted if formatted else raw


def _format_key(key: str) -> str:
    return key.replace("_", " ").strip().title()


def _format_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if value is None or value == "":
        return "—"
    return str(value)


def _format_table(rows: list[dict]) -> str:
    # Column order: first-seen across all rows, not just row 0 - a list
    # entry with an extra/missing key (a tool's dict shape drifting
    # slightly between rows) still gets every column instead of losing
    # whichever key row 0 didn't have.
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    def cell(row: dict, column: str) -> str:
        return _format_scalar(row.get(column, "")).replace("|", "\\|").replace("\n", " ")

    header = "| " + " | ".join(_format_key(c) for c in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(cell(row, c) for c in columns) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _format_list(key: str, items: list) -> str:
    heading = f"**{_format_key(key)}** ({len(items)})"
    if items and all(isinstance(item, dict) for item in items):
        return f"{heading}\n\n{_format_table(items)}"
    return heading + "\n" + "\n".join(f"- {_format_scalar(item)}" for item in items)


def _format_mapping(key: str, value: dict) -> str:
    body = "\n".join(f"- **{_format_key(k)}:** {_format_scalar(v)}" for k, v in value.items())
    return f"**{_format_key(key)}**\n{body}"


def _format_report(report: str) -> str:
    # A fenced block, not a paragraph: `report` strings are preformatted
    # (aligned "Label: value" lines, box-drawing title rules) and would lose
    # that alignment if Markdown collapsed their whitespace like prose.
    return f"```\n{report.strip()}\n```"


def _format_object(data: dict) -> str:
    # `message`/`report` render in their NATURAL position - wherever they
    # fall in `data`'s key order, which mirrors the contract's declared
    # field order (FastMCP serializes a Pydantic model field-by-field, and
    # every contract in capabilities/*/contract.py declares `message` last
    # - see capabilities/README.md's Output formatting section). Earlier
    # versions force-hoisted `message` to the very top as a "lead
    # sentence"; that fought every contract's own field order instead of
    # respecting it - a result like SimulationResult, whose author put the
    # affected-objects/transports lists before `message` on purpose (detail
    # first, verdict last), was shown summary-first regardless. Not
    # hoisting means each contract's declared order IS the display order.
    has_report = isinstance(data.get("report"), str) and bool(data["report"].strip())

    blocks: list[str] = []
    markers = data.get("download_markers")
    if isinstance(markers, list):
        blocks.extend(str(m) for m in markers if m)
    for key, value in data.items():
        if key in {"download_url", "file_path", "remote_filename", "size_bytes", "download_markers"}:
            continue
        if key == "message":
            if isinstance(value, str) and value.strip():
                blocks.append(value.strip())
            continue
        if key == "report":
            if has_report:
                blocks.append(_format_report(value))
            continue
        if value in (None, "", [], {}):
            continue
        if has_report and isinstance(value, dict):
            # A `report` field already renders a nested object's fields
            # in human-readable form (e.g. SumStatusResult.status) -
            # showing the same data again as a raw field list would just
            # repeat it in a second, less readable shape.
            continue
        if isinstance(value, list):
            blocks.append(_format_list(key, value))
        elif isinstance(value, dict):
            blocks.append(_format_mapping(key, value))
        else:
            blocks.append(f"**{_format_key(key)}:** {_format_scalar(value)}")

    return "\n\n".join(blocks)
