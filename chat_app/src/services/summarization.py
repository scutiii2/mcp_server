"""Phase 3 of the token-based conversation-context plan: on-demand
"/summarize" compresses a chat's history into one summary message plus
one cumulative log-attachment message, replacing what's resent to the
LLM. Fully manual (triggered from script.js's "/summarize" command) and
fail-safe - summarize_chat() only ever writes the transcript on a clean
success; any failure raises SummarizeError and leaves storage untouched.

The same summarize_chat() is meant to be the one shared implementation
phase 4's "/clear" and phase 5's auto-trigger both reuse later - not
duplicated per caller.
"""

from __future__ import annotations

import os
from pathlib import Path

from anthropic import Anthropic

from src.services import ai_agent_client, chats_store, usage_limits
from src.utils.catalog import catalog

# Keeps a repeated summarize cycle's summary from ballooning back toward
# the size of the history it's supposed to be replacing.
SUMMARY_TOKEN_CAP = 2000

# Phase 6: bounded retry loop, not a one-shot "count and hope" - each
# recompress attempt re-prompts with an explicit "shorter, still verbatim"
# instruction; caps at this many EXTRA attempts beyond the initial call so
# a stubbornly long model output can't loop forever, only ever accepting
# the cap or giving up and keeping the last (possibly still-oversized)
# attempt.
MAX_RECOMPRESS_ATTEMPTS = 2

# Fraction of context_window at which chat_api's phase 5 pre-send check
# (see __index__.py's _maybe_auto_summarize) transparently runs a
# summarize_chat before the user's actual turn - conceptually the SAME
# number as script.js's own CONTEXT_USAGE_THRESHOLD_RATIO (phase 1's bar
# coloring), kept at the same 0.8 value by hand since Python and the
# browser can't share one literal across that boundary.
AUTO_SUMMARIZE_THRESHOLD_RATIO = 0.8

_CLAUDE_MODEL_PREFIX = "claude"


class SummarizeError(Exception):
    """Raised when summarize_chat() could not produce a usable summary -
    the agent was unreachable, errored, or returned nothing. The caller
    (chat_api's summarize route) must leave the chat's stored transcript
    completely untouched whenever this is raised."""


def build_summarization_prompt(raw_text: str, prior_summary: str | None = None) -> str:
    """The one-shot completion prompt sent through ai_agent's interpret()
    tool. Explicitly instructs the model never to paraphrase structured
    data - this harness executes MCP tool calls straight out of chat
    history, so a summary that rounds off a file path or silently drops
    a digit from an id is a real regression, not just a lossy recap."""
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


def _recompress_prompt(raw_text: str, prior_summary: str | None, oversized_summary: str) -> str:
    base = build_summarization_prompt(raw_text, prior_summary)
    return (
        f"{base}\n\n"
        "Your previous attempt at this summary came back too long:\n\n"
        f"{oversized_summary}\n\n"
        "Write it again, meaningfully shorter, while still preserving "
        "every exact file path, identifier, URL, and tool-call value "
        "verbatim - only the surrounding prose may be cut further."
    )


@catalog
def count_tokens(model: str, text: str) -> int:
    """Token count for `text` under `model` - exact, via the Anthropic
    SDK's count_tokens endpoint (no completion cost), when this process
    has the plain CLAUDE_API_KEY secret_llm.env sets (the same env var
    ai_agent's default "claude" gateway resolves against - see
    ai_agent/configs/config_llms.json - merged into this process's
    environment too by run.py's create_app()); approximate
    (len(text)//4) for every other model, or if that call fails for any
    reason. chat_app deliberately holds no LLM client of its own
    post-migration (see services/llm/settings.py's docstring) - this is
    a best-effort exact count for the common default-gateway case, not a
    hard dependency, and it only ever gates the summary-cap check below,
    never anything billed."""
    if model and model.startswith(_CLAUDE_MODEL_PREFIX):
        api_key = os.getenv("CLAUDE_API_KEY")
        if api_key:
            try:
                client = Anthropic(api_key=api_key)
                result = client.messages.count_tokens(
                    model=model, messages=[{"role": "user", "content": text}]
                )
                return result.input_tokens
            except Exception:  # noqa: BLE001 - falls through to the approximation below
                pass
    return max(1, len(text) // 4)


def summarize_chat(
    db_path: Path, username: str, chat_id: str, agent_url: str, usage_db_path: Path | None = None,
) -> bool:
    """Compresses everything since the last summarize (or the whole
    history, on the first call) into one fresh summary message and one
    cumulative log-attachment message, replacing the chat's stored
    transcript. Returns False (a no-op, not an error) when there's
    nothing new since the last summarize; raises SummarizeError - never
    touching storage - when the agent can't be reached or returns
    nothing usable.

    messages[0] being kind == "summary" is this function's own
    invariant for "already summarized at least once" (see the module
    docstring) - messages[1] is always its paired log-attachment
    whenever that's true, since the two are only ever written together
    below.

    Each interpret() call's total_tokens is logged against username in
    usage_db_path (when given) so summarization spend counts toward the
    same 6-hour/weekly caps as chat turns."""
    chat = chats_store.get_chat(db_path, username, chat_id)
    if chat is None:
        raise SummarizeError("Chat not found.")

    messages = chat["messages"]
    has_prior = bool(messages) and messages[0].get("kind") == "summary"
    prior_summary = messages[0]["content"] if has_prior else None
    prior_log = (messages[1].get("content") or "") if has_prior and len(messages) > 1 else ""
    new_range = messages[2:] if has_prior else messages
    if not new_range:
        return False

    new_range_text = chats_store.render_messages(new_range)
    prompt = build_summarization_prompt(new_range_text, prior_summary)
    summary_text = ""
    model_used = ""
    retries = 0
    while True:
        try:
            result = ai_agent_client.interpret(agent_url, prompt)
        except ai_agent_client.AgentToolError as error:
            # The agent WAS reached and answered - it just declined (e.g.
            # its pinned provider is rate-limited). Deliberately verbatim,
            # same reasoning as chat_api's own "❌ {error}" for ask(): this
            # is exactly the shape ("Error code: 429 - {...'error_type':
            # 'rate_limit_exceeded'...}") script.js's
            # matchOpenRouterDailyLimit/renderErrorMessage already know how
            # to render as a friendly headline + hint, so it must not get
            # wrapped in extra prose here. Only fatal on the FIRST call -
            # a recompress retry failing this way just keeps the prior
            # (possibly over-cap) summary, same as any other retry failure.
            if retries == 0:
                raise SummarizeError(str(error)) from error
            break
        except Exception as error:  # noqa: BLE001 - a genuine connectivity failure, not a tool-reported error
            if retries == 0:
                raise SummarizeError(f"Could not reach the AI agent: {error}") from error
            break

        if usage_db_path is not None:
            usage_limits.record_usage(usage_db_path, username, result.get("total_tokens") or 0)

        text = (result.get("response") or "").strip()
        if not text:
            if retries == 0:
                raise SummarizeError("The AI agent returned an empty summary.")
            break
        summary_text = text
        model_used = result.get("model") or model_used

        if count_tokens(model_used, summary_text) <= SUMMARY_TOKEN_CAP or retries >= MAX_RECOMPRESS_ATTEMPTS:
            break
        retries += 1
        prompt = _recompress_prompt(new_range_text, prior_summary, summary_text)

    new_messages = [
        {"role": "assistant", "kind": "summary", "content": summary_text},
        {"role": "assistant", "kind": "log_attachment", "content": prior_log + new_range_text},
    ]
    chats_store.save_chat(db_path, username, chat_id, new_messages)
    return True
