"""Builds this ai_agent instance's system prompt from its agent file
(agents/<id>.json), once, at import time.

SYSTEM_PROMPT (imported by anthropic_provider.py/openai_provider.py) is
built from, in order: an identity line ("Your name is Ember: <role>", the
role being "Orchestrator" for an orchestrator and the file's label for any
other agent), the file's persona, the orchestrator roster (per request, see
system_prompt_for) and the file's instructions. An agent file with no
instructions gets DEFAULT_INSTRUCTIONS.
"""

from __future__ import annotations

from typing import Sequence

from src.agents import agent_spec
from src.agents.agent_spec import AgentSpec, RosterEntry

APP_NAME = "Ember"
APP_DESCRIPTION = "Support tool that reads real system state through tools instead of manual lookups."
DEFAULT_INSTRUCTIONS = (
    "You are a helpful assistant with access to tools. Use them to get real data rather than guessing, "
    "and say so plainly when no tool can answer the question. Confirm with the user before any "
    "destructive or hard-to-reverse action."
)


def roster_block(roster: Sequence[RosterEntry]) -> str:
    """The orchestrator's view of its specialists, one line each."""
    if not roster:
        return ""
    lines = "\n".join(f"- {r.id} - {r.label}: {r.focus or '(no focus given)'}" for r in roster)
    return (
        "You coordinate these specialist agents. When a part of the request fits one of them "
        "better than you, hand that part to it with delegate_to_agent, then combine the answers:\n"
        f"{lines}"
    )


def _identity(spec: AgentSpec) -> str:
    role = "Orchestrator" if spec.orchestrator else (spec.label or spec.id)
    return (
        f"Your name is {APP_NAME}: {role}, an AI Assistant. {APP_DESCRIPTION} "
        "When asked who you are or what your name is, answer with your name and this role."
    )


def _compose_system_prompt(spec: AgentSpec, roster_text: str = "") -> str:
    parts = (_identity(spec), spec.persona, roster_text, spec.instructions or DEFAULT_INSTRUCTIONS)
    return "\n\n".join(p for p in parts if p)


SYSTEM_PROMPT = _compose_system_prompt(agent_spec.current())

# Appended to SYSTEM_PROMPT per request when chat_app's caveman toggle is on.
# A prompt-level instruction, not a post-process filter: a regex pass would
# risk mangling code blocks, error strings and proper nouns.
CAVEMAN_INSTRUCTIONS = (
    "Respond terse, like a smart caveman. Keep all technical substance; cut "
    "only fluff. Drop articles (a/an/the), filler (just/really/basically), "
    "pleasantries and hedging. Fragments are fine. Use short synonyms. Keep "
    "code blocks, commands, file paths, error messages, identifiers and "
    "numbers exactly as they are. Never drop not/no/never/only/except: they "
    "flip meaning. Use full, plain sentences for warnings and for anything "
    "irreversible or destructive. Write in the language the user writes in."
)


def system_prompt_for(caveman: bool = False, roster: Sequence[RosterEntry] = ()) -> str:
    """SYSTEM_PROMPT, with this turn's orchestrator roster (if any) placed
    before the tool-use instructions, and caveman instructions appended."""
    prompt = _compose_system_prompt(agent_spec.current(), roster_block(roster)) if roster else SYSTEM_PROMPT
    return f"{prompt}\n\n{CAVEMAN_INSTRUCTIONS}" if caveman else prompt
