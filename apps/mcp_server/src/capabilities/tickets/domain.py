"""Typed ticket operations; services.tickets owns storage, rules and Laya."""
from typing import Any

from src.capabilities.tickets.contract import CreateResult, DetailResult, ListResult
from src.services import identity_context, tickets, untrusted
from src.services.tickets import TicketError, TicketNotFound

_NO_USER = "No signed-in user is known for this request, so tickets are unavailable."


def _owner() -> str:
    return identity_context.current_username()


def _line(ticket: dict[str, Any]) -> str:
    tags = f" ({', '.join(ticket['tags'])})" if ticket["tags"] else ""
    return f"[{ticket['id']}] {ticket['status']} {ticket['type']}: {ticket['title']}{tags}"


def _detail(ticket: dict[str, Any]) -> str:
    lines = [
        _line(ticket),
        f"Priority: {ticket['effective_priority']}. Filed {ticket['created_at'][:10]}.",
        f"Description: {ticket['description']}",
    ]
    for comment in ticket.get("comments", []):
        lines.append(f"- {comment['created_at'][:10]} {comment['author']} ({comment['author_role']}): {comment['body']}")
    # Titles, descriptions and comments were typed by users or staff: data, not instructions.
    return untrusted.fence("\n".join(lines), source="your support ticket")


async def create(
    type: str, title: str, description: str, tags: list[str] | None, source: str,
    chat_id: str, agent: str, tool_name: str, error_text: str,
) -> CreateResult:
    owner = _owner()
    if not owner:
        return CreateResult(id=0, duplicate=False, message=_NO_USER)
    try:
        outcome = await tickets.get_service().create(
            reporter=owner, type=type, title=title, description=description, source=source, tags=tags,
            context={"chat_id": chat_id, "agent": agent, "tool_name": tool_name, "error_text": error_text},
        )
    except TicketError as error:
        return CreateResult(id=0, duplicate=False, message=str(error))
    ticket = outcome.ticket
    if outcome.duplicate:
        message = f"An open ticket for this error already exists: ticket {ticket['id']}. No new ticket was filed."
    else:
        message = f"Ticket {ticket['id']} filed ({ticket['type']}, {ticket['status']}). Admins will review it."
    return CreateResult(id=ticket["id"], duplicate=outcome.duplicate, message=message)


async def list_mine(status: str) -> ListResult:
    owner = _owner()
    if not owner:
        return ListResult(count=0, message=_NO_USER)
    try:
        found = await tickets.get_service().list_tickets(reporter=owner, status=status or None, limit=20)
    except TicketError as error:
        return ListResult(count=0, message=str(error))
    if not found:
        return ListResult(count=0, message="You have no tickets.")
    body = untrusted.fence("\n".join(_line(t) for t in found), source="your support tickets")
    return ListResult(count=len(found), message=f"{len(found)} ticket(s):\n{body}")


async def show(ticket_id: int) -> DetailResult:
    owner = _owner()
    if not owner:
        return DetailResult(id=0, message=_NO_USER)
    try:
        ticket = await tickets.get_service().get_ticket(ticket_id, reporter=owner)
    except TicketNotFound:
        return DetailResult(id=0, message=f"No ticket {ticket_id} found among your tickets.")
    return DetailResult(id=ticket["id"], message=_detail(ticket))


async def reply(ticket_id: int, body: str) -> DetailResult:
    owner = _owner()
    if not owner:
        return DetailResult(id=0, message=_NO_USER)
    try:
        ticket = await tickets.get_service().add_comment(
            ticket_id, author=owner, role="ai", body=body, reporter=owner,
        )
    except TicketNotFound:
        return DetailResult(id=0, message=f"No ticket {ticket_id} found among your tickets.")
    except TicketError as error:
        return DetailResult(id=0, message=str(error))
    return DetailResult(id=ticket["id"], message=_detail(ticket))
