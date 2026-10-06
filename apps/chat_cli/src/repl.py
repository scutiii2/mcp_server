"""ChatRepl: the prompt loop, the local commands, and one turn from question to answer.

Everything it talks to is passed in (the client, the console, the line reader),
so tests drive it with fakes. All waiting is async; the one blocking thing, the
prompt, is prompt_toolkit's `prompt_async`."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from rich.console import Console
from rich.table import Table
from rich.text import Text

from src.api import (
    Agent,
    ApiError,
    ChatDetail,
    ChatSummary,
    EmberError,
    SessionExpired,
    TurnGone,
    Usage,
    UsageWindow,
)
from src.events import ConnectionLost, watch_turn
from src.renderer import StreamRenderer, symbols_for
from src.session import ChatSession, title_from

ReadLine = Callable[[str], Awaitable[str]]

HELP = """\
/chats          list your recent chats
/open N         open chat N from the list (and join it if it is still answering)
/new            start a new chat
/ask on|off     ask before each tool runs (off by default)
/usage          show your token usage against the limits
/help           this list
/quit           leave (Ctrl+D works too)
Ctrl+C while an answer is being written stops it."""

TOOLS_NOT_HERE = "Slash commands for tools are not supported in chat_cli; use the web chat."
CHATS_SHOWN = 30


class Client(Protocol):
    async def entry_agent(self) -> Agent: ...
    async def chats(self) -> list[ChatSummary]: ...
    async def chat(self, chat_id: str) -> ChatDetail: ...
    async def start_turn(
        self,
        chat_id: str,
        question: str,
        agent_id: str,
        title: str | None = None,
        ask_before_tools: bool = False,
        allowed_tools: list[str] | None = None,
    ) -> int: ...
    async def cancel(self, chat_id: str) -> None: ...
    async def decide(self, chat_id: str, step_id: str, decision: str) -> None: ...
    async def usage(self) -> Usage: ...
    def stream_events(self, chat_id: str, after: int) -> Any: ...


class ChatRepl:
    def __init__(
        self,
        client: Client,
        console: Console,
        read_line: ReadLine,
        agents: list[Agent],
        session: ChatSession | None = None,
        *,
        ask_tools: bool = False,
        force_approval: bool = False,
        relogin: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self._client = client
        self._console = console
        self._read = read_line
        self.agents = agents
        self.session = session or ChatSession()
        self.ask_tools = ask_tools
        self._forced = force_approval
        self._relogin = relogin
        self._symbols = symbols_for(console)
        self._listed: list[ChatSummary] = []
        self._interrupted = False
        self._ended = False

    # --- the loop ---------------------------------------------------------------------------

    async def run(self) -> None:
        """Reads questions until the person leaves. Needs the session's agent set (main sets the entry agent)."""
        if self.session.agent is None:
            return
        while not self._ended:
            try:
                line = await self._read(self._symbols.prompt)
            except EOFError:
                return
            except KeyboardInterrupt:
                if self._interrupted:
                    return
                self._interrupted = True
                self._say("Press Ctrl+C again or Ctrl+D to leave.", "dim")
                continue
            self._interrupted = False
            text = line.strip()
            if not text:
                continue
            if text.startswith("/"):
                if not await self._command(text):
                    return
                continue
            await self.ask(text)

    def _say(self, message: str, style: str = "") -> None:
        self._console.print(Text(message, style=style))

    # --- local commands ---------------------------------------------------------------------

    async def _command(self, text: str) -> bool:
        """Runs a local command; False means leave."""
        name, _, rest = text.partition(" ")
        rest = rest.strip()
        try:
            if name in ("/quit", "/exit"):
                return False
            if name == "/help":
                self._console.print(Text(HELP))
            elif name == "/new":
                self.session.start_new()
                self._say("New chat.", "dim")
            elif name == "/chats":
                await self._list_chats()
            elif name == "/open":
                await self._open(rest)
            elif name == "/usage":
                await self._show_usage()
            elif name == "/ask":
                self._set_ask(rest)
            else:
                self._say(TOOLS_NOT_HERE, "yellow")
        except SessionExpired:
            if not await self._reconnect():
                return False
            self._say("Logged in again. Run the command again.", "dim")
        except EmberError as error:
            self._say(f"{self._symbols.error} {error}", "red")
        return True

    def _set_ask(self, value: str) -> None:
        if value not in ("on", "off"):
            self._say(f"Asking before tools is {'on' if self.ask_tools else 'off'}. Use /ask on or /ask off.")
            return
        self.ask_tools = value == "on"
        note = " (an administrator requires it for everyone anyway)" if self._forced and not self.ask_tools else ""
        self._say(f"Asking before tools: {value}{note}.", "dim")

    async def _list_chats(self) -> None:
        self._listed = (await self._client.chats())[:CHATS_SHOWN]
        if not self._listed:
            self._say("No saved chats yet.", "dim")
            return
        labels = {a.id: a.label for a in self.agents}
        table = Table(show_edge=False, pad_edge=False)
        for column in ("#", "Title", "Agent", "Messages", "Updated"):
            table.add_column(column)
        for number, chat in enumerate(self._listed, 1):
            title = chat.title + ("  (answering)" if chat.running else "")
            table.add_row(
                str(number), title, labels.get(chat.agent_id or "", chat.agent_id or "-"), str(chat.message_count), chat.updated_at[:16].replace("T", " ")
            )
        self._console.print(table)
        self._say("Open one with /open N.", "dim")

    async def _open(self, number: str) -> None:
        if not number.isdigit() or not 1 <= int(number) <= len(self._listed):
            self._say("Use /chats first, then /open N with a number from the list.", "yellow")
            return
        chat = self._listed[int(number) - 1]
        detail = await self._client.chat(chat.id)
        self.session.open(detail.summary)
        renderer = StreamRenderer(self._console, {a.id: a.label for a in self.agents})
        renderer.print_history(detail.messages)
        if detail.summary.running:
            self._say("Still answering; joining ...", "dim")
            await self._stream(0)

    async def _show_usage(self) -> None:
        usage = await self._client.usage()
        for name, window in (("6 hours", usage.six_hour), ("7 days", usage.weekly)):
            self._say(f"{name}: {self._window_text(window)}")

    @staticmethod
    def _window_text(window: UsageWindow) -> str:
        if window.limit <= 0:
            return f"{window.used:,} tokens (no limit)"
        reset = f", frees up {window.reset_at[:16].replace('T', ' ')} UTC" if window.reset_at else ""
        return f"{window.used:,} of {window.limit:,} tokens{reset}"

    # --- one turn ---------------------------------------------------------------------------

    async def ask(self, question: str) -> None:
        """Sends a question and shows the answer as it is written."""
        agent = self.session.agent
        if agent is None:
            return
        session = self.session
        allowed = None if self._forced else sorted(session.allowed_tools)
        try:
            after = await self._client.start_turn(
                session.chat_id,
                question,
                agent.id,
                title_from(question) if session.is_new else None,
                ask_before_tools=self.ask_tools,
                allowed_tools=allowed,
            )
        except SessionExpired:
            if await self._reconnect():
                self._say("Logged in again. Send the question again.", "dim")
            else:
                self._ended = True
            return
        except ApiError as error:
            self._say(f"{self._symbols.error} {error.detail}", "red")
            return
        except EmberError as error:
            self._say(f"{self._symbols.error} {error}", "red")
            return
        session.is_new = False
        await self._stream(after)

    async def _stream(self, after: int) -> None:
        chat_id = self.session.chat_id
        renderer = StreamRenderer(self._console, {a.id: a.label for a in self.agents})
        answered: set[str] = set()  # a reconnect's snapshot may list a question already answered
        try:
            async for event in watch_turn(self._client, chat_id, after):
                renderer.handle(event)
                for request in self._approvals_in(event):
                    if str(request.get("id", "")) in answered:
                        continue
                    answered.add(str(request.get("id", "")))
                    with renderer.paused():
                        await self._approve(chat_id, request)
        except asyncio.CancelledError:
            # Ctrl+C (asyncio turns it into a cancel of this task): stop the answer, keep the prompt.
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                task.uncancel()
            renderer.finish()
            await self._stop_answer(chat_id)
            return
        except TurnGone:
            renderer.finish()
            self._say("That answer is no longer running. Open the chat with /chats to read it.", "yellow")
            return
        except ConnectionLost as error:
            renderer.finish()
            self._say(f"{self._symbols.error} {error}. The answer carries on; read it later with /chats.", "red")
            return
        except SessionExpired:
            renderer.finish()
            if await self._reconnect():
                self._say("Logged in again. The answer carries on; read it with /chats.", "dim")
            else:
                self._ended = True
            return
        renderer.finish()

    @staticmethod
    def _approvals_in(event: dict[str, Any]) -> list[dict[str, Any]]:
        """The tool runs an event is waiting on the person for. An answer that is already
        waiting when this client joins comes in the snapshot, not as its own event."""
        kind = event.get("type")
        if kind == "approval_request":
            return [event]
        if kind == "snapshot":
            return [dict(a) for a in event.get("approvals") or [] if isinstance(a, dict)]
        return []

    async def _stop_answer(self, chat_id: str) -> None:
        try:
            await self._client.cancel(chat_id)
        except EmberError:
            pass  # stopped reading anyway
        self._say(f"{self._symbols.cancelled} Cancelled", "yellow")

    async def _approve(self, chat_id: str, event: dict[str, Any]) -> None:
        """Asks whether a tool may run, and tells ember_api. Anything but an explicit yes is a no."""
        step_id = str(event.get("id", ""))
        tool = str(event.get("tool", ""))
        always = "" if self._forced else ", [a]lways for this chat"
        try:
            answer = (await self._read(f"Allow this tool? [y]es once{always}, [n]o: ")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        decision = "deny"
        if answer in ("y", "yes"):
            decision = "allow"
        elif answer in ("a", "always"):
            decision = "allow" if self._forced else "always"
        try:
            await self._client.decide(chat_id, step_id, decision)
        except ApiError as error:
            if error.status not in (404, 409):  # already answered, or the answer ended
                self._say(f"{self._symbols.error} {error.detail}", "red")
            return
        except EmberError as error:
            self._say(f"{self._symbols.error} {error}", "red")
            return
        if decision == "always":
            self.session.allowed_tools.add(tool)

    async def _reconnect(self) -> bool:
        """The session ended: log in again if the caller can. False means leave."""
        self._say("Your session ended.", "yellow")
        if self._relogin is None or not await self._relogin():
            return False
        return True
