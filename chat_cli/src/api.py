"""EmberClient: ember_api's REST and event-stream API, as chat_cli uses it.

Every call is async. The login cookie stays in the client's cookie jar (memory
only); nothing is written to disk. Errors are turned into `EmberError`s whose
messages are fit to show a person.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from src.sse import SseParser

USER_AGENT = "chat_cli/0.1"
REQUEST_TIMEOUT = httpx.Timeout(10.0, read=60.0)
# An answer can take minutes between events: no read timeout on the stream.
STREAM_TIMEOUT = httpx.Timeout(10.0, read=None)


class EmberError(Exception):
    """Anything that went wrong talking to ember_api."""


class EmberUnreachable(EmberError):
    """ember_api did not answer (down, wrong address, network)."""


class ApiError(EmberError):
    """ember_api answered with an error status. `detail` is its own message."""

    def __init__(self, status: int, detail: str, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.retry_after = retry_after


class SessionExpired(ApiError):
    """401 on a call that needs a login."""


class TurnGone(EmberError):
    """No answer is being written for the chat (it finished, and the replay expired)."""


@dataclass(frozen=True)
class Agent:
    id: str
    label: str


@dataclass(frozen=True)
class ChatSummary:
    id: str
    title: str
    agent_id: str | None
    message_count: int
    updated_at: str
    running: bool


@dataclass(frozen=True)
class ChatDetail:
    summary: ChatSummary
    messages: list[dict[str, Any]]


@dataclass(frozen=True)
class UsageWindow:
    used: int
    limit: int  # 0 = unlimited
    reset_at: str | None


@dataclass(frozen=True)
class Usage:
    six_hour: UsageWindow
    weekly: UsageWindow


def _summary(data: dict[str, Any]) -> ChatSummary:
    return ChatSummary(
        id=str(data["id"]),
        title=str(data.get("title", "")),
        agent_id=data.get("agent_id"),
        message_count=int(data.get("message_count", 0)),
        updated_at=str(data.get("updated_at", "")),
        running=bool(data.get("running", False)),
    )


def _window(data: dict[str, Any]) -> UsageWindow:
    return UsageWindow(used=int(data.get("used", 0)), limit=int(data.get("limit", 0)), reset_at=data.get("reset_at"))


def error_detail(response: httpx.Response) -> str:
    """FastAPI's `detail` (a string, or a list of field errors), else the status."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict) and first.get("msg"):
            where = ".".join(str(p) for p in first.get("loc", ())[1:])
            return f"{where}: {first['msg']}" if where else str(first["msg"])
    return f"ember_api answered {response.status_code}"


class EmberClient:
    def __init__(self, base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, *, body: Any = None, login: bool = False) -> Any:
        try:
            response = await self._http.request(method, path, json=body)
        except httpx.HTTPError as error:
            raise EmberUnreachable(f"Cannot reach ember_api at {self._http.base_url}: {error}") from error
        return self._checked(response, login=login)

    @staticmethod
    def _checked(response: httpx.Response, login: bool = False) -> Any:
        if response.status_code >= 400:
            retry = response.headers.get("Retry-After", "")
            retry_after = int(retry) if retry.isdigit() else None
            detail = error_detail(response)
            if response.status_code == 401 and not login:
                raise SessionExpired(401, detail or "Your session ended", retry_after)
            raise ApiError(response.status_code, detail, retry_after)
        return response.json() if response.content else None

    # --- account ----------------------------------------------------------------------------

    async def login(self, username: str, password: str) -> dict[str, Any]:
        return await self._request("POST", "/api/auth/login", body={"username": username, "password": password}, login=True)

    async def logout(self) -> None:
        try:
            await self._request("POST", "/api/auth/logout", body={})
        except EmberError:
            pass  # leaving anyway; the session expires on its own

    async def agents(self) -> list[Agent]:
        return [Agent(id=str(a["id"]), label=str(a.get("label", a["id"]))) for a in await self._request("GET", "/api/agents")]

    async def force_tool_approval(self) -> bool:
        """Whether an administrator requires approval for every tool. A failed read means no."""
        try:
            return bool((await self._request("GET", "/api/settings")).get("force_tool_approval", False))
        except EmberError:
            return False

    async def usage(self) -> Usage:
        data = await self._request("GET", "/api/usage")
        return Usage(six_hour=_window(data["six_hour"]), weekly=_window(data["weekly"]))

    # --- chats ------------------------------------------------------------------------------

    async def chats(self) -> list[ChatSummary]:
        return [_summary(c) for c in await self._request("GET", "/api/chats")]

    async def chat(self, chat_id: str) -> ChatDetail:
        data = await self._request("GET", f"/api/chats/{chat_id}")
        return ChatDetail(summary=_summary(data), messages=list(data.get("messages", [])))

    async def start_turn(
        self,
        chat_id: str,
        question: str,
        agent_id: str,
        title: str | None = None,
        ask_before_tools: bool = False,
        allowed_tools: list[str] | None = None,
    ) -> int:
        """Saves the question and starts the answer. Returns the sequence to watch events after."""
        body: dict[str, Any] = {"question": question, "agent_id": agent_id, "caveman": False, "enabled_extensions": []}
        if title:
            body["title"] = title
        if ask_before_tools:
            body["ask_before_tools"] = True
            body["allowed_tools"] = allowed_tools or []
        data = await self._request("POST", f"/api/chats/{chat_id}/turns", body=body)
        return int(data["sequence"])

    async def cancel(self, chat_id: str) -> None:
        await self._request("POST", f"/api/chats/{chat_id}/cancel", body={})

    async def decide(self, chat_id: str, step_id: str, decision: str) -> None:
        await self._request("POST", f"/api/chats/{chat_id}/approvals", body={"step_id": step_id, "decision": decision})

    # --- events -----------------------------------------------------------------------------

    async def stream_events(self, chat_id: str, after: int) -> AsyncIterator[dict[str, Any]]:
        """The turn's events newer than `after`, as they arrive, until the stream ends.
        Raises TurnGone (404), SessionExpired (401) or EmberUnreachable (other failures)."""
        try:
            async with self._http.stream(
                "GET",
                f"/api/chats/{chat_id}/events",
                params={"after": after},
                headers={"Accept": "text/event-stream"},
                timeout=STREAM_TIMEOUT,
            ) as response:
                if response.status_code == 404:
                    raise TurnGone("No answer is being written for this chat")
                if response.status_code == 401:
                    raise SessionExpired(401, "Your session ended")
                if response.status_code >= 400:
                    raise EmberUnreachable(f"ember_api answered {response.status_code}")
                parser = SseParser()
                async for text in response.aiter_text():
                    for event in parser.feed(text):
                        yield event
        except httpx.HTTPError as error:
            raise EmberUnreachable(str(error)) from error
