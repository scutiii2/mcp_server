"""Chat summarization (port of chat_app/src/services/summarization.py).

Compresses everything since the last summary into one "summary" message
plus one cumulative "log_attachment" message holding the raw transcript it
replaced. The summary is what the agent sees from then on; the log is kept
for the reader and the export but never resent to the agent.

Fail-safe: the caller writes the new transcript only when a usable summary
came back - any failure raises SummarizeError and nothing changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.services.agent_gateway import AgentCallError, AgentGateway, Caller

# Keeps repeated summaries from growing back toward the history they replace.
SUMMARY_TOKEN_CAP = 2000
MAX_RECOMPRESS_ATTEMPTS = 2

SUMMARY = "summary"
LOG_ATTACHMENT = "log_attachment"


class SummarizeError(Exception):
    """No usable summary; the stored chat must stay untouched."""


@dataclass(frozen=True)
class SummaryOutcome:
    messages: list[dict[str, Any]]
    # Every interpret() result, for usage accounting.
    results: list[dict[str, Any]]


def approx_tokens(text: str) -> int:
    """ember_api holds no tokenizer; ~4 characters per token (chat_app's
    fallback for every non-Claude model)."""
    return max(1, len(text) // 4)


def render_messages(messages: list[dict[str, Any]]) -> str:
    """Plain-text transcript, one "--- header ---" block per message (same
    layout as chat_app's chats_store.render_messages)."""
    lines = []
    for message in messages:
        header = "command" if message.get("kind") == "command" else str(message.get("role", "unknown"))
        meta = []
        if message.get("model"):
            meta.append(str(message["model"]))
        if isinstance(message.get("total_tokens"), int):
            meta.append(f"{message['total_tokens']} tokens")
        if meta:
            header = f"{header} ({', '.join(meta)})"
        lines += [f"--- {header} ---", str(message.get("content") or ""), ""]
    return "\n".join(lines)


def history_for_agent(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """What ask() gets as history: role + content, without the raw log a
    summary already replaced (resending it would undo the summary)."""
    return [
        {"role": m["role"], "content": m["content"]}
        for m in messages
        if m.get("kind") != LOG_ATTACHMENT and m.get("role") in ("user", "assistant")
    ]


def last_context_usage(messages: list[dict[str, Any]]) -> tuple[int | None, int | None]:
    """The last assistant turn's (context_tokens, context_window)."""
    tokens = window = None
    for m in messages:
        t, w = m.get("context_tokens"), m.get("context_window")
        if isinstance(t, int) and isinstance(w, int):
            tokens, window = t, w
    return tokens, window


def needs_summary(messages: list[dict[str, Any]], max_context: int, ratio: float) -> bool:
    """True once the last turn used `ratio` of the smaller of the model's
    context window and the configured per-chat cap."""
    tokens, window = last_context_usage(messages)
    if not tokens or not window or window <= 0:
        return False
    if max_context:
        window = min(window, max_context)
    return tokens / window >= ratio


def build_prompt(raw_text: str, prior_summary: str | None = None) -> str:
    instructions = (
        "Summarize the conversation transcript below into a concise, dense "
        "briefing a continuing assistant can use as its only memory of "
        "everything that happened so far. Preserve every exact file path, "
        "identifier, URL, and tool-call argument/result value VERBATIM - "
        "never paraphrase, round, or approximate a structured value; copy "
        "it exactly as written, character for character. Prose narration "
        "around those values may be condensed freely. Write plain prose, "
        "with no meta-commentary about the summarization task itself."
    )
    if prior_summary:
        return (
            f"{instructions}\n\n"
            "You are UPDATING an existing summary with a new stretch of "
            "conversation that happened since it was written. Produce ONE "
            "fresh summary that folds the prior summary and the new "
            "transcript together - do not just append the new part onto "
            "the old summary text.\n\n"
            f"--- PRIOR SUMMARY ---\n{prior_summary}\n\n"
            f"--- NEW TRANSCRIPT SINCE THAT SUMMARY ---\n{raw_text}"
        )
    return f"{instructions}\n\n--- TRANSCRIPT ---\n{raw_text}"


def _recompress_prompt(raw_text: str, prior_summary: str | None, oversized: str) -> str:
    return (
        f"{build_prompt(raw_text, prior_summary)}\n\n"
        f"Your previous attempt at this summary came back too long:\n\n{oversized}\n\n"
        "Write it again, meaningfully shorter, while still preserving "
        "every exact file path, identifier, URL, and tool-call value "
        "verbatim - only the surrounding prose may be cut further."
    )


def split_prior(messages: list[dict[str, Any]]) -> tuple[str | None, str, list[dict[str, Any]]]:
    """(prior summary, prior raw log, messages since them)."""
    if messages and messages[0].get("kind") == SUMMARY:
        prior_log = str(messages[1].get("content") or "") if len(messages) > 1 else ""
        return str(messages[0].get("content") or ""), prior_log, messages[2:]
    return None, "", messages


def cleared(messages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The "just clear" variant: no summary, one cumulative raw log of
    everything (None when there's nothing to clear)."""
    _prior_summary, prior_log, new_range = split_prior(messages)
    if not new_range:
        return None
    return [{"role": "assistant", "kind": LOG_ATTACHMENT, "content": prior_log + render_messages(new_range)}]


async def summarize(
    gateway: AgentGateway, url: str, caller: Caller, messages: list[dict[str, Any]]
) -> SummaryOutcome | None:
    """The new transcript, or None when nothing is new since the last
    summary. Raises SummarizeError when no summary could be made."""
    prior_summary, prior_log, new_range = split_prior(messages)
    if not new_range:
        return None

    raw_text = render_messages(new_range)
    prompt = build_prompt(raw_text, prior_summary)
    results: list[dict[str, Any]] = []
    summary = ""
    for attempt in range(MAX_RECOMPRESS_ATTEMPTS + 1):
        try:
            result = await gateway.interpret(url, caller, prompt)
        except AgentCallError as error:
            if attempt == 0:
                raise SummarizeError(str(error)) from error
            break  # keep the previous (longer) summary
        results.append(result)
        text = str(result.get("response") or "").strip()
        if not text:
            if attempt == 0:
                raise SummarizeError("The agent returned an empty summary.")
            break
        summary = text
        if approx_tokens(summary) <= SUMMARY_TOKEN_CAP:
            break
        prompt = _recompress_prompt(raw_text, prior_summary, summary)

    return SummaryOutcome(
        messages=[
            {"role": "assistant", "kind": SUMMARY, "content": summary},
            {"role": "assistant", "kind": LOG_ATTACHMENT, "content": prior_log + raw_text},
        ],
        results=results,
    )
