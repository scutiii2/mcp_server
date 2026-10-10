"""Support tickets: validation, automatic-report guards, tagging, Laya grouping and
priority elevation. The service never raises because Laya is down; it just
skips grouping and tagging. Ticket text is never logged.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.config import settings
from src.services import ticket_rules as rules
from src.services.redact import redact
from src.services.ticket_config import TicketConfig, load_ticket_config
from src.services.ticket_store import AutoLimit, TicketStore

logger = logging.getLogger(__name__)

TITLE_MAX = 120
DESCRIPTION_MAX = 4000
COMMENT_MAX = 2000
_CONTEXT_LIMITS = {"chat_id": 200, "agent": 100, "tool_name": 100, "error_text": 2000}
_VERIFIED_MAX_CHARS = 200


class TicketError(ValueError):
    """A request tickets cannot honour; the message is safe to show a user or model."""


class TicketNotFound(LookupError):
    """No such ticket or group, or not visible to the requester."""


@dataclass(frozen=True)
class CreateOutcome:
    ticket: dict[str, Any]
    duplicate: bool
    group_size: int


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any, name: str, limit: int) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise TicketError(f"The {name} is required.")
    if len(clean) > limit:
        raise TicketError(f"The {name} is {len(clean)} characters; the limit is {limit}.")
    return clean


def _reported_context(context: dict[str, Any] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, limit in _CONTEXT_LIMITS.items():
        value = (context or {}).get(key)
        if value:
            result[key] = redact(str(value))[0][:limit]
    return result


def _verified_context(context: dict[str, Any] | None) -> dict[str, str]:
    return {str(key)[:50]: str(value)[:_VERIFIED_MAX_CHARS] for key, value in list((context or {}).items())[:10]}


class TicketService:
    def __init__(self, store: TicketStore, config: TicketConfig, laya: Any = None,
                 *, clock: Callable[[], datetime] | None = None) -> None:
        self._store = store
        self._config = config
        self._laya = laya
        self._clock = clock or _utc_now

    def _now(self) -> datetime:
        return self._clock()

    @staticmethod
    async def _db(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(lambda: function(*args, **kwargs))

    # ---- create -------------------------------------------------------

    async def create(
        self, *, reporter: str, type: str, title: str, description: str, source: str = "user",
        tags: list[str] | None = None, context: dict[str, Any] | None = None,
        verified_context: dict[str, Any] | None = None,
    ) -> CreateOutcome:
        reporter = str(reporter or "").strip()
        if not reporter:
            raise TicketError("No signed-in reporter is known for this request, so a ticket cannot be filed.")
        if type not in rules.TYPES:
            raise TicketError(f"The type must be one of: {', '.join(rules.TYPES)}.")
        if source not in rules.SOURCES:
            raise TicketError(f"The source must be one of: {', '.join(rules.SOURCES)}.")
        title = _text(title, "title", TITLE_MAX)
        description = _text(description, "description", DESCRIPTION_MAX)
        reported = _reported_context(context)
        if source != "user":  # written by a model from tool output: never store secrets
            title, description = redact(title)[0], redact(description)[0]

        fingerprint = None
        if source == "ai_auto":
            fingerprint = rules.fingerprint(reported.get("tool_name"), reported.get("error_text") or title)
            existing = await self._db(self._store.find_open_auto, reporter, fingerprint)
            if existing:
                return await self._outcome(existing, duplicate=True)

        draft = {"type": type, "title": title, "description": description}
        tag_list = rules.clean_tags(tags, self._config.tags)
        laya_ok = self._laya is not None
        if not tag_list and laya_ok:
            tag_list, laya_ok = await self._laya_tag(draft)
        group_id, possible = (None, None)
        if laya_ok:
            group_id, possible = await self._match_group(draft, tag_list)

        now = self._now()
        try:
            ticket_id, created, group_id = await self._db(
                self._store.insert_ticket, reporter=reporter, type=type, title=title, description=description,
                source=source, tags=tag_list,
                context={"reported": reported, "verified": _verified_context(verified_context)},
                fingerprint=fingerprint, group_id=group_id, possible_group_id=possible, now=now.isoformat(),
                auto_cap=self._config.auto_hourly_cap if source == "ai_auto" else None,
                auto_since=(now - timedelta(hours=1)).isoformat(),
            )
        except AutoLimit:
            raise TicketError(
                f"Too many automatic reports from this account in the last hour "
                f"(limit {self._config.auto_hourly_cap}); not filing another one."
            ) from None
        if created:
            await self._reelevate(group_id)
        return await self._outcome(ticket_id, duplicate=not created)

    async def _outcome(self, ticket_id: int, *, duplicate: bool) -> CreateOutcome:
        ticket = await self._db(self._store.get_ticket, ticket_id)
        total, _ = await self._db(self._store.group_counts, ticket["group_id"], self._since())
        return CreateOutcome(ticket=ticket, duplicate=duplicate, group_size=total)

    def _since(self) -> str:
        return (self._now() - timedelta(hours=self._config.recent_hours)).isoformat()

    async def _laya_tag(self, draft: dict[str, Any]) -> tuple[list[str], bool]:
        try:
            tag = await self._laya.pick_tag(draft, self._config.tags)
        except Exception:
            logger.warning("Ticket tagging skipped: Laya is unavailable.")
            return [], False
        return ([tag] if tag else []), True

    async def _match_group(self, draft: dict[str, Any], tags: list[str]) -> tuple[int | None, int | None]:
        candidates = await self._db(self._store.candidates, draft["type"], tags, self._config.laya_candidates)
        possible: int | None = None
        for candidate in candidates:
            try:
                verdict = await self._laya.same_issue(draft, candidate)
            except Exception:
                logger.warning("Ticket grouping skipped: Laya is unavailable.")
                return None, possible
            if verdict == "yes":
                return candidate["group_id"], None
            if verdict == "uncertain" and possible is None:
                possible = candidate["group_id"]
        return None, possible

    async def _reelevate(self, group_id: int) -> None:
        """Raise the group's priority from its size and recent rate unless an admin pinned it."""
        group = await self._db(self._store.get_group, group_id)
        if group is None or group["priority_pinned"]:
            return
        total, recent = await self._db(self._store.group_counts, group_id, self._since())
        raised = rules.elevated_priority(group["priority"], total, recent, self._config.elevation)
        if raised != group["priority"]:
            await self._db(self._store.update_group, group_id, priority=raised, now=self._now().isoformat())


    # ---- reads --------------------------------------------------------

    async def _visible(self, ticket_id: int, reporter: str | None) -> dict[str, Any]:
        ticket = await self._db(self._store.get_ticket, ticket_id)
        # Someone else's ticket looks exactly like a missing one.
        if ticket is None or (reporter is not None and ticket["reporter"] != reporter):
            raise TicketNotFound(f"No ticket {ticket_id}.")
        return ticket

    async def _with_comments(self, ticket_id: int) -> dict[str, Any]:
        ticket = await self._db(self._store.get_ticket, ticket_id)
        ticket["comments"] = await self._db(self._store.list_comments, ticket_id)
        return ticket

    async def get_ticket(self, ticket_id: int, *, reporter: str | None = None) -> dict[str, Any]:
        await self._visible(ticket_id, reporter)
        return await self._with_comments(ticket_id)

    @staticmethod
    def _check(value: str | None, allowed: tuple[str, ...], name: str) -> None:
        if value is not None and value not in allowed:
            raise TicketError(f"The {name} must be one of: {', '.join(allowed)}.")

    async def list_tickets(
        self, *, reporter: str | None = None, status: str | None = None, type: str | None = None,
        tag: str | None = None, priority: str | None = None, assignee: str | None = None,
        group_id: int | None = None, possible_only: bool = False, limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._check(status, rules.STATUSES, "status")
        self._check(type, rules.TYPES, "type")
        self._check(priority, rules.PRIORITIES, "priority")
        return await self._db(
            self._store.list_tickets, reporter=reporter, status=status, type=type, tag=tag, priority=priority,
            assignee=assignee, group_id=group_id, possible_only=possible_only, limit=max(1, min(limit, 500)),
        )

    async def list_groups(
        self, *, status: str | None = None, tag: str | None = None, priority: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._check(status, rules.STATUSES, "status")
        self._check(priority, rules.PRIORITIES, "priority")
        return await self._db(
            self._store.list_groups, since=self._since(), status=status, tag=tag, priority=priority,
            limit=max(1, min(limit, 500)),
        )

    async def stats(self) -> dict[str, int]:
        return await self._db(self._store.stats)

    # ---- changes ------------------------------------------------------

    async def add_comment(
        self, ticket_id: int, *, author: str, role: str, body: str, reporter: str | None = None,
    ) -> dict[str, Any]:
        await self._visible(ticket_id, reporter)
        self._check(role, ("reporter", "staff", "ai"), "role")
        text = _text(body, "comment", COMMENT_MAX)
        if role == "ai":
            text = redact(text)[0]
        await self._db(self._store.add_comment, ticket_id, author, role, text, self._now().isoformat())
        return await self._with_comments(ticket_id)

    async def close_own(self, ticket_id: int, reporter: str) -> dict[str, Any]:
        await self._visible(ticket_id, reporter)
        await self._db(self._store.update_ticket, ticket_id, {"status": "closed"}, self._now().isoformat())
        return await self._with_comments(ticket_id)

    async def update_ticket(
        self, ticket_id: int, *, status: str | None = None, priority: str | None = None,
        assignee: str | None = None, tags: list[str] | None = None,
    ) -> dict[str, Any]:
        self._check(status, rules.STATUSES, "status")
        self._check(priority, rules.PRIORITIES, "priority")
        await self._visible(ticket_id, None)
        changes: dict[str, Any] = {}
        if status is not None:
            changes["status"] = status
        if priority is not None:
            changes["priority"] = priority
        if assignee is not None:
            changes["assignee"] = assignee.strip() or None
        if tags is not None:
            changes["tags"] = rules.clean_tags(tags, self._config.tags)
        if changes:
            await self._db(self._store.update_ticket, ticket_id, changes, self._now().isoformat())
        return await self._with_comments(ticket_id)

    async def move_ticket(self, ticket_id: int, group_id: int | None) -> dict[str, Any]:
        await self._visible(ticket_id, None)
        target = await self._db(self._store.move_ticket, ticket_id, group_id, self._now().isoformat())
        if target is None:
            raise TicketNotFound(f"No group {group_id}.")
        await self._reelevate(target)
        return await self._with_comments(ticket_id)

    async def set_group_priority(
        self, group_id: int, *, priority: str | None = None, pinned: bool | None = None,
    ) -> dict[str, Any]:
        self._check(priority, rules.PRIORITIES, "priority")
        if await self._db(self._store.get_group, group_id) is None:
            raise TicketNotFound(f"No group {group_id}.")
        if priority is not None and pinned is None:
            pinned = True  # a hand-set priority is pinned until an admin unpins it
        await self._db(self._store.update_group, group_id, priority=priority, pinned=pinned, now=self._now().isoformat())
        if pinned is False:
            await self._reelevate(group_id)
        return await self._db(self._store.get_group, group_id)


_service: TicketService | None = None


def get_service() -> TicketService:
    """The shared service, built on first use from settings and configs/config_tickets.json."""
    global _service
    if _service is None:
        config = load_ticket_config(settings.tickets_config_path)
        laya = None
        if settings.laya_url:
            from src.services.ticket_laya import TicketLaya
            from src.services.ticket_laya_transport import McpLayaTransport

            laya = TicketLaya(
                McpLayaTransport(settings.laya_url, settings.internal_api_token),
                min_confidence=config.laya_min_confidence, timeout=config.laya_timeout_seconds,
            )
        _service = TicketService(TicketStore(settings.tickets_db_path), config, laya)
    return _service
