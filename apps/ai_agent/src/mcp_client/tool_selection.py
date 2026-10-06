"""Laya-based tool identification: before a turn's first model call, Laya (a
local model) can shortlist the MCP tools most relevant to the question, so the
model is offered fewer tool schemas.

Settings come from configs/config_tool_selection.json. Off by default - Laya
needs torch and a one-time ~1.6GB weight download. Shortlisting never blocks a
turn: any failure (Laya missing, model load error) offers the full tool list.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Iterable, Protocol

import anyio.to_thread

from src.core.catalog import catalog
from src.core.config_files import TOOL_SELECTION_PATH, read_section

_CONFIG_PATH = TOOL_SELECTION_PATH
_config: dict[str, Any] | None = None


def _load_config() -> dict[str, Any]:
    global _config
    if _config is not None:
        return _config
    raw = read_section(_CONFIG_PATH, "tool_selection", {})
    if not isinstance(raw, dict):
        raise ValueError("config_tool_selection.json tool_selection must be an object")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("config_tool_selection.json tool_selection enabled must be true or false")
    top_k = raw.get("top_k", 20)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise ValueError("config_tool_selection.json tool_selection top_k must be a positive integer")
    _config = {"enabled": enabled, "top_k": top_k}
    return _config


@catalog
def is_enabled() -> bool:
    """Whether Laya tool identification is switched on for this agent."""
    return _load_config()["enabled"]


@catalog
def top_k() -> int:
    """How many tools Laya keeps when shortlisting."""
    return _load_config()["top_k"]


@catalog
def reset_cache() -> None:
    """Clear the cached config, e.g. after the file is edited."""
    global _config
    _config = None


_LAYA_MODEL_ID = "convaiinnovations/laya"  # English-only checkpoint; pinned so
# laya.load() does not also download the multilingual model.
_log = logging.getLogger(__name__)


class ToolRanker(Protocol):
    def rank(self, question: str, options: dict[str, str], k: int) -> list[str]:
        """The `k` option names (keys of `options`) that best fit `question`."""


class LayaToolRanker:
    """Ranks tools by embedding similarity using Laya's `shortlist_choice`.
    The model loads on first use and is shared by every turn."""

    def __init__(self) -> None:
        self._agent: Any = None
        self._embed: Any = None
        self._lock = threading.Lock()

    def _load(self) -> tuple[Any, Any]:
        with self._lock:
            if self._agent is None:
                import laya

                agent = laya.load(_LAYA_MODEL_ID)
                self._embed = laya.embed_fn_from_agent(agent)
                self._agent = agent
            return self._agent, self._embed

    def rank(self, question: str, options: dict[str, str], k: int) -> list[str]:
        import laya

        _, embed = self._load()
        return list(laya.shortlist_choice(question, options, embed, k))

    def rank_with_scores(self, question: str, options: dict[str, str], k: int) -> tuple[list[str], list[float] | None]:
        """Like rank, plus Laya's signed cosine per kept label (rank order).
        Scores are None when k covers every option (nothing was dropped)."""
        import laya

        _, embed = self._load()
        labels, scores = laya.shortlist_choice(question, options, embed, k, return_scores=True)
        return list(labels), (list(scores) if scores is not None else None)


_default_ranker = LayaToolRanker()


def default_ranker() -> LayaToolRanker:
    """The process-wide Laya ranker - tool shortlisting and agent routing
    share one loaded model."""
    return _default_ranker


@catalog
async def shortlist_schemas(
    question: str,
    schemas: list[dict[str, Any]],
    always_keep: Iterable[str] = (),
    ranker: ToolRanker | None = None,
) -> list[dict[str, Any]]:
    """Cut `schemas` down to the `top_k` tools that best fit `question`, in
    their original order. Tools named in `always_keep` stay and do not count
    toward `top_k`. Returns `schemas` unchanged when the setting is off, when
    there are no more than `top_k` rankable tools, or when ranking fails.

    Works for both providers' schema shapes - only each entry's `name` and
    `description` are read. Ranking runs on a worker thread so a slow first
    model load does not block the event loop.
    """
    if not is_enabled():
        return schemas
    keep_always = set(always_keep)
    k = top_k()
    options = {s["name"]: s.get("description") or "" for s in schemas if s["name"] not in keep_always}
    if len(options) <= k:
        return schemas
    try:
        chosen = await anyio.to_thread.run_sync((ranker or _default_ranker).rank, question, options, k)
    except Exception:
        _log.warning("Laya tool shortlist failed; offering every tool", exc_info=True)
        return schemas
    keep = set(chosen) | keep_always
    return [s for s in schemas if s["name"] in keep]
