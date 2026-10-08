"""Asking the user before a tool runs.

A provider's tool loop calls `review()` between announcing a step
(`step_start`) and running it. What happens depends on the turn's
`ApprovalPolicy`, which ember_api sets per `ask()` call:

* ``off``   - nothing is asked (the default; chat_app never sets a policy).
* ``ask``   - an ``approval_request`` event goes to the caller, and the tool
  runs only after the user answers through the ``decide`` MCP tool. No answer
  in time, a refusal, or a Stop all mean the tool does not run.
* ``deny``  - a tool needing approval is refused outright. A delegated agent
  gets this: it has no channel back to the user, so it cannot ask.

A tool named in the policy's `ask_prefixes` asks even when the mode is
``off`` (and is refused under ``deny``). Once a private tool has run in a
turn the policy is `tainted`: from then on every tool asks, because the
private server's output is untrusted text that could steer the model (a tool
the user already allowed for the chat still runs without asking).

The policy travels in a ContextVar, like tool_progress.py's sink, so the two
providers' signatures stay as they are and the worker thread that runs
``delegate_to_agent`` (which copies the context) can read it.

The wait polls for cancellation, so Stop ends it within `POLL_SECONDS`.
Every failure path is a refusal, never a run: the tool starts only on an
explicit "allow" or "always" for that exact request and step.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from src.llm import cancellation
from src.llm.base_provider import ChatCancelled, OnEvent, step_event

APPROVAL_MODES = ("off", "ask", "deny")
DECISIONS = ("allow", "always", "deny")

# Under ember_api's 5-minute read timeout on a streaming ask() call, with room to spare.
DECISION_TIMEOUT_SECONDS = 240.0
POLL_SECONDS = 0.5

DECLINED = "The user declined to run this tool, so it was not run. Do not retry it; say what you could not do."
TIMED_OUT = "The user did not answer in time, so this tool was not run."
NO_CHANNEL = "This tool needs the user's approval, but there is no way to ask them from here, so it was not run."
DELEGATED = "This tool needs the user's approval, which a delegated agent cannot ask for, so it was not run."


@dataclass
class ApprovalPolicy:
    mode: str = "off"
    # Tools the user already allowed for this chat, and any they allow with
    # "always" during this turn.
    allowed_tools: set[str] = field(default_factory=set)
    # Tools whose name starts with one of these always need approval, even in
    # mode "off" (the user's own MCP servers - see private_extensions/turn.py).
    ask_prefixes: tuple[str, ...] = ()
    # Set once a private tool has run this turn: its output is text from a server
    # we do not control and could steer the model, so from then on every tool
    # asks (see mcp_upstream._call_private).
    tainted: bool = False

    def __post_init__(self) -> None:
        if self.mode not in APPROVAL_MODES:
            raise ValueError(f"approval_mode must be one of {', '.join(APPROVAL_MODES)}, not {self.mode!r}")

    def needs_approval(self, tool: str) -> bool:
        return tool not in self.allowed_tools and (
            self.mode != "off" or self.tainted or tool.startswith(self.ask_prefixes)
        )

_DEFAULT = ApprovalPolicy()
_policy: ContextVar[ApprovalPolicy] = ContextVar("approval_policy", default=_DEFAULT)


def bind(policy: ApprovalPolicy) -> Token:
    return _policy.set(policy)


def reset(token: Token) -> None:
    _policy.reset(token)


def current() -> ApprovalPolicy:
    return _policy.get()


def mark_tainted() -> None:
    """Every later tool this turn asks (see ApprovalPolicy.tainted). A turn
    without its own policy shares the default one with every caller, which is
    never changed."""
    policy = _policy.get()
    if policy is not _DEFAULT:
        policy.tainted = True


class ApprovalBroker:
    """The approvals waiting on a user, keyed by (request_id, step_id).

    `decide()` and `wait()` both run on the server's event loop (the `decide`
    MCP tool is async), so futures are set and awaited on the same loop.
    """

    def __init__(self, timeout: float = DECISION_TIMEOUT_SECONDS, poll: float = POLL_SECONDS) -> None:
        self._timeout = timeout
        self._poll = poll
        self._pending: dict[tuple[str, str], asyncio.Future[str]] = {}

    def pending(self, request_id: str) -> list[str]:
        return [step for (request, step) in self._pending if request == request_id]

    async def wait(self, request_id: str, step_id: str) -> str:
        """The user's decision (`allow`, `always` or `deny`), or `timeout` /
        `cancelled`. A second wait on the same step replaces the first,
        which then reads as denied."""
        loop = asyncio.get_running_loop()
        key = (request_id, step_id)
        previous = self._pending.get(key)
        if previous is not None and not previous.done():
            previous.set_result("deny")
        future: asyncio.Future[str] = loop.create_future()
        self._pending[key] = future
        deadline = loop.time() + self._timeout
        try:
            while True:
                if cancellation.is_cancelled(request_id):
                    return "cancelled"
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return "timeout"
                try:
                    return await asyncio.wait_for(asyncio.shield(future), min(self._poll, remaining))
                except asyncio.TimeoutError:
                    continue
        finally:
            if self._pending.get(key) is future:
                del self._pending[key]

    def decide(self, request_id: str, step_id: str, decision: str) -> bool:
        """Answers a pending approval. False when there is none: unknown
        step, already answered, or the turn moved on. Each is answered once."""
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
        future = self._pending.get((request_id, step_id))
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True


BROKER = ApprovalBroker()


async def review(
    request_id: str | None,
    step_id: str,
    tool: str,
    label: str | None,
    arguments: dict[str, Any],
    on_event: OnEvent | None,
) -> str | None:
    """None when the tool may run; otherwise the text to give the model in
    place of a result (the tool is not run). Raises ChatCancelled if the user
    stops the turn while it waits."""
    policy = current()
    if not policy.needs_approval(tool):
        return None
    if policy.mode == "deny":
        return DELEGATED
    if on_event is None or not request_id:
        return NO_CHANNEL

    await on_event(step_event("approval_request", id=step_id, tool=tool, label=label, arguments=arguments))
    outcome = await BROKER.wait(request_id, step_id)
    await on_event(step_event("approval_resolved", id=step_id, outcome=outcome))

    if outcome == "always":
        policy.allowed_tools.add(tool)
        return None
    if outcome == "allow":
        return None
    if outcome == "cancelled":
        await on_event(step_event("step_end", id=step_id, ok=False, result="Stopped before it ran."))
        raise ChatCancelled()
    return TIMED_OUT if outcome == "timeout" else DECLINED
