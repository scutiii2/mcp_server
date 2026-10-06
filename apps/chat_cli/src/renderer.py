"""StreamRenderer: draws a turn's events in the terminal with rich.

Answer text appears as live Markdown. A tool run commits the text so far, then
prints its own line, so the order on screen is the order things happened. The
renderer only draws; asking the person (tool approvals) is the REPL's job."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

REFRESH_SECONDS = 0.1
RESULT_LINE_MAX = 120
ARGUMENTS_MAX = 600


@dataclass(frozen=True)
class Symbols:
    running: str
    ok: str
    failed: str
    cancelled: str
    error: str
    prompt: str


UNICODE = Symbols(running="⏳", ok="✓", failed="✗", cancelled="⏹", error="❌", prompt="you › ")
ASCII = Symbols(running="[..]", ok="[ok]", failed="[x]", cancelled="[stopped]", error="[error]", prompt="you > ")


def symbols_for(console: Console) -> Symbols:
    """Unicode marks, unless the console cannot encode them."""
    return UNICODE if "utf" in (console.encoding or "").lower() else ASCII


def first_line(text: str, limit: int = RESULT_LINE_MAX) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line if len(line) <= limit else line[: limit - 1] + "…"


class StreamRenderer:
    def __init__(self, console: Console, agent_labels: Mapping[str, str] | None = None) -> None:
        self._console = console
        self._labels = dict(agent_labels or {})
        self.symbols = symbols_for(console)
        self._live: Live | None = None
        self._text = ""
        self._streamed = False  # any answer text was shown, so `final` need not show it again
        self._steps: dict[str, str] = {}
        self._last_refresh = 0.0

    # --- one event --------------------------------------------------------------------------

    def handle(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "token":
            self._add_text(str(event.get("text", "")))
        elif kind == "token_reset":
            self._text = ""
            self._refresh(force=True)
        elif kind == "snapshot":
            self._text = str(event.get("text", ""))
            self._streamed = self._streamed or bool(self._text)
            self._refresh(force=True)
            for request in event.get("approvals") or []:
                if isinstance(request, dict):
                    self._commit()
                    self._approval_card(request)
        elif kind == "step_start":
            self._commit()
            label = str(event.get("label") or event.get("tool") or "tool")
            self._steps[str(event.get("id", ""))] = label
            self._console.print(Text(f"{self.symbols.running} {label}", style="dim"))
        elif kind == "step_end":
            self._step_end(event)
        elif kind == "approval_request":
            self._commit()
            self._approval_card(event)
        elif kind == "cancelling":
            self._console.print(Text("Cancelling ...", style="dim"))
        elif kind == "summarizing":
            self._console.print(Text("Summarizing the chat so far ...", style="dim"))
        elif kind == "final":
            self._final(event)
        elif kind == "error":
            self._commit()
            self._console.print(Text(f"{self.symbols.error} {event.get('message', 'The answer failed')}", style="red"))
        # approval_resolved, usage, step_progress, summarized: nothing to draw

    def _step_end(self, event: dict[str, Any]) -> None:
        label = self._steps.get(str(event.get("id", "")), "tool")
        if event.get("ok"):
            self._console.print(Text(f"{self.symbols.ok} {label}", style="dim green"))
        else:
            reason = first_line(str(event.get("result", "")))
            suffix = f": {reason}" if reason else ""
            self._console.print(Text(f"{self.symbols.failed} {label}{suffix}", style="red"))

    def _approval_card(self, event: dict[str, Any]) -> None:
        label = str(event.get("label") or event.get("tool") or "tool")
        arguments = json.dumps(event.get("arguments", {}), ensure_ascii=False, default=str)
        if len(arguments) > ARGUMENTS_MAX:
            arguments = arguments[: ARGUMENTS_MAX - 1] + "…"
        self._console.print(Text(f"The agent wants to run: {label} ({event.get('tool', '')})", style="bold yellow"))
        self._console.print(Text(f"  arguments: {arguments}", style="yellow"))

    def _final(self, event: dict[str, Any]) -> None:
        message = event.get("message") or {}
        if not self._streamed and message.get("content"):
            self._text = str(message["content"])
            self._streamed = True
        self._commit()
        if event.get("cancelled"):
            self._console.print(Text(f"{self.symbols.cancelled} Cancelled", style="yellow"))
        footer = self.footer(message)
        if footer:
            self._console.print(Text(footer, style="dim"))

    def footer(self, message: Mapping[str, Any]) -> str:
        """`Agent · model · 90/30 tokens · 1.2 s`, leaving out what the message lacks."""
        parts: list[str] = []
        agent = message.get("agent")
        if agent:
            parts.append(self._labels.get(str(agent), str(agent)))
        if message.get("model"):
            parts.append(str(message["model"]))
        inp, out, total = message.get("input_tokens"), message.get("output_tokens"), message.get("total_tokens")
        if inp is not None and out is not None:
            parts.append(f"{inp}/{out} tokens")
        elif total is not None:
            parts.append(f"{total} tokens")
        if message.get("duration_s") is not None:
            parts.append(f"{float(message['duration_s']):.1f} s")
        return " · ".join(parts) if self.symbols is UNICODE else " | ".join(parts)

    # --- live text --------------------------------------------------------------------------

    def _add_text(self, text: str) -> None:
        if not text:
            return
        self._text += text
        self._streamed = True
        self._refresh()

    def _refresh(self, force: bool = False) -> None:
        if not self._text:
            return
        if self._live is None:
            self._live = Live(Markdown(self._text), console=self._console, auto_refresh=False, vertical_overflow="visible")
            self._live.start()
            self._last_refresh = time.monotonic()
            return
        now = time.monotonic()
        if force or now - self._last_refresh >= REFRESH_SECONDS:
            self._live.update(Markdown(self._text), refresh=True)
            self._last_refresh = now

    def _commit(self) -> None:
        """Shows the text so far for good, and starts a fresh block for what comes next."""
        if self._live is not None:
            self._live.update(Markdown(self._text), refresh=True)
            self._live.stop()
            self._live = None
            if not self._console.is_terminal:
                # Piped output: rich leaves the line open there (a terminal gets its newline from the live region).
                self._console.print()
        elif self._text:
            self._console.print(Markdown(self._text))
        self._text = ""

    def finish(self) -> None:
        """Ends the turn on screen: whatever text is still live is committed."""
        self._commit()
        self._streamed = False

    @contextmanager
    def paused(self) -> Iterator[None]:
        """Stops the live region while the person is being asked something, so the
        prompt is not redrawn over."""
        self._commit()
        yield

    # --- printing saved messages ------------------------------------------------------------

    def print_history(self, messages: list[dict[str, Any]]) -> None:
        """A saved chat, as it would have looked."""
        for message in messages:
            kind = message.get("kind")
            if kind == "log_attachment":
                continue
            content = str(message.get("content", ""))
            if kind == "summary":
                self._console.print(Text("(earlier messages were summarized)", style="dim"))
            elif kind == "command":
                self._console.print(Text(content, style="dim"))
            elif message.get("role") == "user":
                self._console.print(Text(f"{self.symbols.prompt}{content}", style="bold"))
            else:
                self._console.print(Markdown(content))
                footer = self.footer(message)
                if footer:
                    self._console.print(Text(footer, style="dim"))
