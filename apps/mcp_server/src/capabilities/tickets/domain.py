"""Typed ticket operations; services.tickets owns storage, rules and Laya."""
from typing import Any

from src.capabilities.tickets.contract import CreateResult, DetailResult, ListResult
from src.config import settings
from src.services import identity_context, tickets, untrusted
from src.services.internal_token import is_exposed_without_token
from src.services.tickets import TicketError, TicketNotFound

_NO_USER = "No signed-in user is known for this request, so tickets are unavailable."


def _identity() -> tuple[str, str]:
    """(the caller's uid, a refusal message). The uid owns the tickets, so a rename or a reused
    username never moves them. A non-empty refusal means no ticket may be touched."""
    if is_exposed_without_token(settings.host, settings.internal_api_token):
        # Without the token any machine that can reach the port could claim any uid.
        return "", (
            f"Tickets are disabled: this server listens on {settings.host!r} without INTERNAL_API_TOKEN, "
            "so anyone on the network could read tickets. Set INTERNAL_API_TOKEN, or bind to 127.0.0.1."
        )
    owner = identity_context.current_uid()
    return owner, ("" if owner else _NO_USER)


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
    owner, refusal = _identity()
    if refusal:
        return CreateResult(id=0, duplicate=False, message=refusal)
    try:
        outcome = await tickets.get_service().create(
            owner=owner, reporter=identity_context.current_username(), type=type, title=title, description=description, source=source, tags=tags,
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
    owner, refusal = _identity()
    if refusal:
        return ListResult(count=0, message=refusal)
    try:
        found = await tickets.get_service().list_tickets(owner=owner, status=status or None, limit=20)
    except TicketError as error:
        return ListResult(count=0, message=str(error))
    if not found:
        return ListResult(count=0, message="You have no tickets.")
    body = untrusted.fence("\n".join(_line(t) for t in found), source="your support tickets")
    return ListResult(count=len(found), message=f"{len(found)} ticket(s):\n{body}")


async def show(ticket_id: int) -> DetailResult:
    owner, refusal = _identity()
    if refusal:
        return DetailResult(id=0, message=refusal)
    try:
        ticket = await tickets.get_service().get_ticket(ticket_id, owner=owner)
    except TicketNotFound:
        return DetailResult(id=0, message=f"No ticket {ticket_id} found among your tickets.")
    return DetailResult(id=ticket["id"], message=_detail(ticket))


async def reply(ticket_id: int, body: str) -> DetailResult:
    owner, refusal = _identity()
    if refusal:
        return DetailResult(id=0, message=refusal)
    try:
        ticket = await tickets.get_service().add_comment(
            ticket_id, author=identity_context.current_username() or owner, role="ai", body=body, owner=owner,
        )
    except TicketNotFound:
        return DetailResult(id=0, message=f"No ticket {ticket_id} found among your tickets.")
    except TicketError as error:
        return DetailResult(id=0, message=str(error))
    return DetailResult(id=ticket["id"], message=_detail(ticket))
