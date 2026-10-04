"""Token usage per agent: the row each ask() returns in agent_usage, and a
local JSONL copy of it so usage is visible even for callers that never go
through ember (chat_cli, direct MCP calls, tests).

One file per agent per UTC day (data/usage/YYYY-MM-DD.<agent id>.jsonl),
so two agent processes never write the same file. Writing never fails a
turn: an error is logged and the turn carries on.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import anyio.to_thread

from src.llm.base_provider import ChatResult

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "usage"
_log = logging.getLogger(__name__)
# Serializes appends within this process. A threading lock, not an
# asyncio one: writes run on worker threads, and tests use many loops.
_lock = threading.Lock()


def usage_dir() -> Path:
    return Path(os.getenv("AI_AGENT_USAGE_DIR") or _DEFAULT_DIR)


def own_row(
    result: ChatResult,
    *,
    agent_id: str,
    agent_label: str,
    gateway: str | None,
    started_at: str,
    finished_at: str,
    delegated_by: str | None,
) -> dict[str, Any]:
    """This agent's own agent_usage entry for one ask() (delegated agents
    add their own rows - see delegation.py)."""
    return {
        "agent_id": agent_id,
        "agent_label": agent_label,
        "provider_id": result.provider_id,
        "gateway": gateway,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "total_tokens": result.total_tokens,
        "started_at": started_at,
        "finished_at": finished_at,
        "delegated_by": delegated_by,
    }


def _write(row: dict[str, Any], directory: Path) -> None:
    path = directory / f"{row['finished_at'][:10]}.{row['agent_id']}.jsonl"
    with _lock:
        directory.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row) + "\n")


async def append(row: dict[str, Any], directory: Path | None = None) -> None:
    try:
        await anyio.to_thread.run_sync(_write, row, directory or usage_dir())
    except Exception:
        _log.warning("could not write the usage log", exc_info=True)
