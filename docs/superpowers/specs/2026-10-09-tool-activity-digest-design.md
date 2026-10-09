# Tool-activity digest for chat history

Date: 2026-10-09
Status: design approved, not implemented
Source: `_TODO.md`, "Close the agentic-harness gaps in ai_agent", items 4 and 5

## Problem

After a turn ends, the model forgets what its tools returned and which tools it ran.

- `ember_api` stores a `steps` list on every assistant message (tool, arguments, ok, result; result capped at `STEP_RESULT_MAX` = 4000 characters, at most `MAX_STEPS` = 50 steps).
- `summarization.history_for_agent` sends the agent only `role` and `content`, so `steps` never reach the model on the next turn.
- `summarization.render_messages` also reads only `content`. The summary prompt promises to keep "tool-call argument/result values" verbatim, but the summarizer never sees them.

Compaction itself (item 5 in the TODO) already exists: `services/summarization.py` and `TurnRegistry._auto_summarize` summarize when the last turn used `auto_summarize_ratio` (0.6) of the context window, with a 2,000-token cap, re-compression, and a raw `log_attachment`. `ai_agent`'s `trim_history_to_fit` is only a fallback. This spec therefore covers item 4 and the small part of item 5 that depends on it (the summarizer seeing tool activity).

## Decision

Send past tool activity as a text digest appended to earlier assistant messages. Rejected alternatives:

- Structured `tool_use` / `tool_result` blocks in history. Needs a provider-neutral stored format, a translator per provider, and a looser `validate_history`. Much larger and riskier.
- Do nothing.

The history contract between `ember_api` and `ai_agent` stays text-only. No change in `ai_agent`, `ember_web` or `chat_cli`.

## Design

### New module: `apps/Ember/ember_api/src/services/step_digest.py`

One responsibility: turn a message's stored `steps` into a short text block.

Interface (names are a proposal; keep them if nothing better fits the surrounding code):

- `digest(steps, *, full: bool) -> str`. Returns `""` when there is nothing to show.
  - `full=True`: one line per step with tool name, a short arguments summary, the result, and a failed marker when `ok` is false.
  - `full=False`: a single line listing tool names only.

Rules:

- Skip steps whose tool is `update_plan` or `ask_user` (local tools, not tool knowledge). Keep `delegate_to_agent`; its result is the specialist's answer.
- Argument summary: compact JSON of `arguments`, cut to 200 characters.
- Result: cut to 300 characters.
- A full digest is capped at 1,500 characters in total; cut at a line boundary and mark the cut.
- The block opens with a fixed label stating that it is a record of earlier tool output, not instructions. The label is a module constant so tests can pin it.
- No step is invented: a step with `ok` of `None` (never finished) is shown as not finished.

Limits are module constants: `RECENT_FULL_MESSAGES = 3`, `RESULT_MAX = 300`, `ARGS_MAX = 200`, `DIGEST_MAX = 1500`.

### Change: `summarization.history_for_agent`

- Still returns `role` and `content` only, and still drops `log_attachment` messages.
- For an assistant message that has `steps`, the returned `content` is the answer text followed by the digest block.
- The last `RECENT_FULL_MESSAGES` assistant messages that have steps get `full=True`. Older ones get `full=False` (tool names only). So digest size does not grow with chat length.
- The digest is built at send time only. Nothing about it is stored, so shared chats, exports and the stored data are unchanged.

### Change: `summarization.render_messages`

- New keyword `include_steps: bool = False`. When true, each assistant message with steps gets its digest (`full=True`, no recency limit) after its content.
- `summarize()` and `build_prompt` use `include_steps=True` for the text sent to the summarizer. The `log_attachment` content is built with the default (`False`), so the reader-facing raw log is unchanged.

### Interaction with auto-summarize

The trigger uses the last turn's measured `context_tokens`. Digests are part of what is sent, so they count automatically. No change to the trigger or the ratio.

## Safety

Tool results can hold text from web pages or files. Persisting that into history as assistant text raises prompt-injection exposure. Mitigations:

- The fixed label marks the block as a record, not instructions.
- Per-result and per-digest caps limit how much foreign text re-enters the prompt.
- Only the last three tool-using messages carry results; older ones carry names only.

Known residual risk: the model may imitate the digest format in its own answers. Accepted; the label wording is pinned by a test so a change is deliberate.

## Testing (pytest in `apps/Ember/ember_api`)

- `digest`: argument and result truncation, total cap with cut marker, skipped tools, failed marker, unfinished step, names-only mode, empty input.
- `history_for_agent`: digest appended for assistant messages with steps; unchanged for user messages and messages without steps; only the last three tool-using messages are full; `log_attachment` still dropped.
- `render_messages`: default output unchanged; `include_steps=True` adds the digest.
- `summarize`: the prompt text contains the digest; the stored `log_attachment` does not.
- Label wording is pinned.

Run the whole `ember_api` suite before finishing (839 tests as of 2026-10-07); there must be no new failures.

## Out of scope

- Structured tool blocks in history.
- Any change in `ai_agent` (including `trim_history_to_fit` and `validate_history`).
- Any `ember_web` or `chat_cli` change.
- Persistent memory and sandboxed workspace (TODO items 6 and 7).

## After implementation

Update the `_TODO.md` section: mark item 4 done, and rewrite item 5 to say that summarizing already existed and the remaining part (summarizer sees tool activity) is covered here.
