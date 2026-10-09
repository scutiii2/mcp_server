# Laya as a question-only provider

Date: 2026-10-09. Scope: `apps/ai_agent`.

## Problem

Laya has a 512-token context window. Tool shortlisting puts every MCP tool
schema plus the question through it, so the input nearly always overflows and
ranking is unreliable. Laya is only dependable for short typed questions
(`choice`, `score`, `noul`) over a short text. The current provider also
hardcodes one triage schema, so no other question can be asked.

## Decision

1. Remove every Laya use except the provider.
2. Make the provider generic: the caller supplies the questions.
3. Any "ask Laya first, escalate to a real LLM if unsure" logic lives in the
   orchestrator LLM, which reads the `uncertain` flags. No cascade code is
   added.

## Removal

- Delete `src/mcp_client/tool_selection.py` and `tests/test_tool_selection.py`.
- Delete the `tool_selection` section from `configs/config_tuning.json` and
  `configs/config_tuning.json.example`, and its entry in `configs/README.md`.
- `src/llm/anthropic_provider.py`, `src/llm/openai_provider.py`: remove the
  `tool_selection` import and the `shortlist_schemas` calls. Models get the
  full tool list.
- `src/agents/agent_routing.py`: remove the ranker, `resolve_auto` and the
  Laya branch. `roster_for` returns every specialist for an orchestrator, `[]`
  otherwise.
- `src/agents/agent_spec.py`: remove the `routing` block (`laya`, `top_k`,
  `allow_auto`, `min_score`). Remove `agent_id="auto"` from
  `delegate_to_agent` (`agents/delegation.py`, providers' tool definition).
- `agents/ember.json`: remove its `routing` entry (it would fail to load
  otherwise). Update affected tests (`test_agent_spec.py`,
  `test_agent_routing.py`, `test_delegation` if present).
- Docs: `README.md` routing rows and Laya routing paragraphs, `src/README.md`
  entries for `tool_selection.py` and `agent_routing.py`.
- Keep the `laya` extra in `pyproject.toml`.

## Provider contract (`src/llm/laya_provider.py`)

### Request

The `question` string is JSON:

```json
{
  "text": "short text to judge",
  "min_confidence": 0.7,
  "questions": {
    "q1": {"type": "choice", "instructions": "...", "criteria": {"a": "...", "b": "..."}},
    "q2": {"type": "score",  "instructions": "...", "criteria": ["low", "mid", "high"]},
    "q3": {"type": "noul",   "instructions": "...", "criteria": {"false": "...", "true": "..."}}
  }
}
```

Validation (all failures raise `ValueError` with a message the orchestrator
can act on; nothing reaches the model):

- Valid JSON object with only `text`, `questions`, `min_confidence`.
- `text`: non-empty string, at most 4000 characters (existing limit).
- `questions`: 1 to 8 entries; ids are non-empty strings.
- Each question: only `type`, `instructions`, `criteria`. `type` is `choice`,
  `score` or `noul`. `instructions` is a non-empty string.
- `choice` criteria: dict of 2 to 10 non-empty string keys and string values.
- `score` criteria: list of 2 to 10 strings.
- `noul` criteria: optional dict with exactly the keys `false` and `true`.
- `min_confidence`: optional number in (0, 1], default `MIN_CONFIDENCE` 0.7.
- Text after the first JSON object is ignored, because delegation appends attachment references to the question string.

### Inference

Unchanged mechanism: one `predict(text, questions, max_len=512)` call under
the existing lock. Raise `ValueError` when `usage.truncated` or
`usage.state_tokens_dropped` is set, so a partly read input never returns an
answer. The question count and option limits above bound how much of the 512
tokens the question heads use.

### Response

`ChatResult.response` is a JSON string, not prose:

```json
{"answers": {
  "q1": {"type": "choice", "choice": "a", "probabilities": {"a": 0.81, "b": 0.19},
         "answer_confidence": 0.81, "uncertain": false},
  "q2": {"type": "score", "score": 1.7, "legend": {"0": "low", "1": "mid", "2": "high"},
         "answer_confidence": 0.62, "uncertain": true},
  "q3": {"type": "noul", "noul": 0.93, "answer_confidence": 0.93, "uncertain": false}
 },
 "uncertain": true}
```

- `uncertain` per question: `answer_confidence < min_confidence`. Top-level
  `uncertain` is true if any question is.
- A `choice` answer is never treated as certain when Laya picks an option the
  request did not define: that raises `ValueError` ("invalid result").
- All numbers are validated finite and in range, as today.
- `output_tokens` stays 0 and `context_tokens` stays `None`.
- No tools, history, free text, summarization or LLM fallback.
  `run_interpret` keeps raising.

### Triage example

The old fixed triage (category, severity, needs_investigation) becomes one
example request in the README and `scripts/check_laya_triage.py`. The
tracked "Laya-only Triage Assistant" agent stays; its `focus` text describes
the request schema so an orchestrator LLM can build it.

## Orchestrator use

An orchestrator delegates a request JSON to a Laya agent through
`delegate_to_agent`. The result is JSON the orchestrator parses. If
`uncertain` is true it may answer itself or delegate to a real-LLM
specialist. This is prompt-level behavior, with no code in ai_agent.

## Testing

- Provider validation: one test per rejection rule above.
- Provider happy path per question type using an injected fake engine
  (existing pattern); confidence gating; custom `min_confidence`; truncation
  rejection; invalid engine output rejection.
- Removal: `agent_spec` rejects a `routing` key as unknown; `roster_for`
  returns the full roster; no module imports `tool_selection`.
- Update `scripts/check_laya_triage.py` to send the triage request JSON.
  It needs the real model, so it is run manually, not in the test suite.
- Run the ai_agent test suite.

## Out of scope

- Automatic cascade code.
- Re-ranking specialists or tools by any other method.
- ember_api / ember_web changes, except removing the one comment in
  `ember_api/src/services/agent_gateway.py:180` if it becomes false.
