"""HTTP routes for support tickets, mounted like /download (see run.py).

Plain HTTP, not tools: ember_api is the caller. Every request needs
X-Internal-Token. The requester comes from X-Requester-Username and is the only
source of the reporter's identity. Reporter routes (/tickets) only ever touch
the requester's own tickets; staff routes (/ticket-admin) see everything and
are called by ember_api only for accounts allowed to manage tickets. These
routes stay up when the `tickets` capability is switched off.
"""

from __future__ import annotations

import hmac
from functools import wraps
from typing import Any, Awaitable, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import settings
from src.services import tickets
from src.services.identity_context import REQUESTER_USERNAME_HEADER
from src.services.tickets import TicketError, TicketNotFound


def _token_valid(request: Request) -> bool:
    expected = settings.internal_api_token
    if not expected:
        return False
    return hmac.compare_digest(expected, request.headers.get("X-Internal-Token", ""))


def _requester(request: Request) -> str:
    username = request.headers.get(REQUESTER_USERNAME_HEADER, "").strip()
    if not username:
        raise TicketError("No requester was named for this request.")
    return username


async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        raise TicketError("The request body must be JSON.") from None
    if not isinstance(data, dict):
        raise TicketError("The request body must be a JSON object.")
    return data


def _int_param(request: Request, name: str, default: int | None = None) -> int | None:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise TicketError(f"{name} must be a whole number.") from None


def _filters(request: Request) -> dict[str, Any]:
    query = request.query_params
    return {
        "status": query.get("status") or None, "type": query.get("type") or None, "tag": query.get("tag") or None,
        "priority": query.get("priority") or None, "assignee": query.get("assignee") or None,
        "group_id": _int_param(request, "group_id"), "possible_only": query.get("possible") == "1",
        "limit": _int_param(request, "limit", 100),
    }


Handler = Callable[[Request], Awaitable[JSONResponse]]


def _guarded(handler: Handler) -> Handler:
    @wraps(handler)
    async def wrapper(request: Request) -> JSONResponse:
        if not _token_valid(request):
            return JSONResponse({"error": "Invalid or missing internal API token"}, status_code=401)
        try:
            return await handler(request)
        except TicketNotFound as error:
            return JSONResponse({"error": str(error)}, status_code=404)
        except TicketError as error:
            return JSONResponse({"error": str(error)}, status_code=400)

    return wrapper


# ---- reporter routes -----------------------------------------------------

@_guarded
async def create_ticket(request: Request) -> JSONResponse:
    reporter = _requester(request)
    data = await _body(request)
    outcome = await tickets.get_service().create(
        reporter=reporter, type=str(data.get("type", "")), title=data.get("title", ""),
        description=data.get("description", ""), source=str(data.get("source") or "user"),
        tags=data.get("tags") if isinstance(data.get("tags"), list) else None,
        context=data.get("context") if isinstance(data.get("context"), dict) else None,
        verified_context=data.get("verified_context") if isinstance(data.get("verified_context"), dict) else None,
    )
    payload = {"ticket": outcome.ticket, "duplicate": outcome.duplicate, "group_size": outcome.group_size}
    return JSONResponse(payload, status_code=200 if outcome.duplicate else 201)


@_guarded
async def list_own(request: Request) -> JSONResponse:
    filters = _filters(request)
    filters["possible_only"] = False
    result = await tickets.get_service().list_tickets(reporter=_requester(request), **filters)
    return JSONResponse({"tickets": result})


@_guarded
async def get_own(request: Request) -> JSONResponse:
    ticket = await tickets.get_service().get_ticket(request.path_params["ticket_id"], reporter=_requester(request))
    return JSONResponse({"ticket": ticket})


@_guarded
async def comment_own(request: Request) -> JSONResponse:
    reporter = _requester(request)
    data = await _body(request)
    ticket = await tickets.get_service().add_comment(
        request.path_params["ticket_id"], author=reporter, role="ai" if data.get("role") == "ai" else "reporter",
        body=data.get("body", ""), reporter=reporter,
    )
    return JSONResponse({"ticket": ticket})


@_guarded
async def close_own(request: Request) -> JSONResponse:
    ticket = await tickets.get_service().close_own(request.path_params["ticket_id"], _requester(request))
    return JSONResponse({"ticket": ticket})


# ---- staff routes --------------------------------------------------------

@_guarded
async def staff_list(request: Request) -> JSONResponse:
    return JSONResponse({"tickets": await tickets.get_service().list_tickets(**_filters(request))})


@_guarded
async def staff_get(request: Request) -> JSONResponse:
    return JSONResponse({"ticket": await tickets.get_service().get_ticket(request.path_params["ticket_id"])})


@_guarded
async def staff_patch(request: Request) -> JSONResponse:
    data = await _body(request)
    ticket = await tickets.get_service().update_ticket(
        request.path_params["ticket_id"], status=data.get("status"), priority=data.get("priority"),
        assignee=data.get("assignee"), tags=data.get("tags") if isinstance(data.get("tags"), list) else None,
    )
    return JSONResponse({"ticket": ticket})


@_guarded
async def staff_comment(request: Request) -> JSONResponse:
    author = _requester(request)
    data = await _body(request)
    ticket = await tickets.get_service().add_comment(
        request.path_params["ticket_id"], author=author, role="staff", body=data.get("body", ""),
    )
    return JSONResponse({"ticket": ticket})


@_guarded
async def staff_move(request: Request) -> JSONResponse:
    data = await _body(request)
    group_id = data.get("group_id")
    if group_id is not None and (isinstance(group_id, bool) or not isinstance(group_id, int)):
        raise TicketError("group_id must be a whole number or null.")
    ticket = await tickets.get_service().move_ticket(request.path_params["ticket_id"], group_id)
    return JSONResponse({"ticket": ticket})


@_guarded
async def staff_groups(request: Request) -> JSONResponse:
    filters = _filters(request)
    groups = await tickets.get_service().list_groups(
        status=filters["status"], tag=filters["tag"], priority=filters["priority"], limit=filters["limit"],
    )
    return JSONResponse({"groups": groups})


@_guarded
async def staff_patch_group(request: Request) -> JSONResponse:
    data = await _body(request)
    pinned = data.get("pinned")
    if pinned is not None and not isinstance(pinned, bool):
        raise TicketError("pinned must be true or false.")
    group = await tickets.get_service().set_group_priority(
        request.path_params["group_id"], priority=data.get("priority"), pinned=pinned,
    )
    return JSONResponse({"group": group})


@_guarded
async def staff_stats(request: Request) -> JSONResponse:
    return JSONResponse(await tickets.get_service().stats())


def install_ticket_routes(app: Starlette) -> None:
    app.add_route("/tickets", create_ticket, methods=["POST"])
    app.add_route("/tickets", list_own, methods=["GET"])
    app.add_route("/tickets/{ticket_id:int}", get_own, methods=["GET"])
    app.add_route("/tickets/{ticket_id:int}/comments", comment_own, methods=["POST"])
    app.add_route("/tickets/{ticket_id:int}/close", close_own, methods=["POST"])
    app.add_route("/ticket-admin/tickets", staff_list, methods=["GET"])
    app.add_route("/ticket-admin/tickets/{ticket_id:int}", staff_get, methods=["GET"])
    app.add_route("/ticket-admin/tickets/{ticket_id:int}", staff_patch, methods=["PATCH"])
    app.add_route("/ticket-admin/tickets/{ticket_id:int}/comments", staff_comment, methods=["POST"])
    app.add_route("/ticket-admin/tickets/{ticket_id:int}/move", staff_move, methods=["POST"])
    app.add_route("/ticket-admin/groups", staff_groups, methods=["GET"])
    app.add_route("/ticket-admin/groups/{group_id:int}", staff_patch_group, methods=["PATCH"])
    app.add_route("/ticket-admin/stats", staff_stats, methods=["GET"])
