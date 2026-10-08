"""The browser's only way to ai_agent and mcp_server: the entry agent and the
MCP proxy (Streamable HTTP: POST messages, GET event stream, DELETE session)."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from src.config import Settings
from src.deps import get_settings, require_permission, require_any_permission
from src.models import Account
from src.services.agent_directory import NO_AGENT_RUNNING, AgentDirectory
from src.services.mcp_policy import AGENT_POLICY, SERVER_POLICY, SERVER_VIEW_POLICY, McpPolicy, PolicyViolation
from src.services.mcp_proxy import McpProxy
from src.services.permissions import CHAT_USE, TOOLS_VIEW, TOOLS_EXECUTE

router = APIRouter(prefix="/api", tags=["mcp"])

MAX_BODY_BYTES = 1_000_000

require_chat = require_permission(CHAT_USE)
require_tools = require_any_permission(TOOLS_VIEW, TOOLS_EXECUTE)

_PROXY_METHODS = ["GET", "POST", "DELETE"]


def get_agent_directory(request: Request) -> AgentDirectory:
    return request.app.state.agent_directory


def get_proxy(request: Request) -> McpProxy:
    return request.app.state.mcp_proxy


class AgentOut(BaseModel):
    # No URL: where the internal servers live stays server-side.
    id: str
    label: str


@router.get("/agent")
async def entry_agent(
    _account: Account = Depends(require_chat),
    directory: AgentDirectory = Depends(get_agent_directory),
) -> AgentOut:
    """The agent every question goes to; ember_web shows its name."""
    agent = await directory.entry()
    if agent is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_AGENT_RUNNING)
    return AgentOut(id=agent.id, label=agent.label)


class ModelTierOut(BaseModel):
    tier: str
    id: str
    use_for: str


class AgentListItem(AgentOut):
    entry: bool
    orchestrator: bool
    focus: str
    status: Literal["running", "offline", "disabled"]
    provider: str | None
    gateway: str | None
    model: str | None
    tiers: list[ModelTierOut]


@router.get("/agents")
async def list_agents(
    _account: Account = Depends(require_chat),
    directory: AgentDirectory = Depends(get_agent_directory),
) -> list[AgentListItem]:
    """Every agent for the Agents page, running or not (see
    AgentDirectory.listing). The entry agent is flagged; an empty list means
    no agent is running and none is defined."""
    return [
        AgentListItem(
            id=a.id, label=a.label, entry=a.entry, orchestrator=a.orchestrator, focus=a.focus, status=a.status,
            provider=a.provider, gateway=a.gateway, model=a.model,
            tiers=[ModelTierOut(tier=t.tier, id=t.id, use_for=t.use_for) for t in a.tiers],
        )
        for a in await directory.listing()
    ]


async def _checked_body(request: Request, policy: McpPolicy) -> bytes | Response | None:
    """The POST body if the policy allows it, a JSON-RPC error response if
    not, or None for GET/DELETE (no body)."""
    if request.method != "POST":
        return None
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Request body too large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Request body too large")
    try:
        payload: Any = json.loads(body)
    except ValueError:
        return _jsonrpc_error(None, -32700, "Parse error")
    try:
        policy.check(payload)
    except PolicyViolation as violation:
        request_id = payload.get("id") if isinstance(payload, dict) else None
        return _jsonrpc_error(request_id, -32601, str(violation), http_status=403)
    return body


def _jsonrpc_error(request_id: Any, code: int, message: str, http_status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=http_status,
    )


@router.api_route("/mcp/agents/{agent_id}", methods=_PROXY_METHODS)
async def proxy_agent(
    agent_id: str,
    request: Request,
    account: Account = Depends(require_chat),
    directory: AgentDirectory = Depends(get_agent_directory),
    proxy: McpProxy = Depends(get_proxy),
) -> Response:
    agent = await directory.get(agent_id)
    if agent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown agent")
    body = await _checked_body(request, AGENT_POLICY)
    if isinstance(body, Response):
        return body
    return await proxy.forward(request, agent.url, account, body, target="ai_agent")


@router.api_route("/mcp/server", methods=_PROXY_METHODS)
async def proxy_server(
    request: Request,
    account: Account = Depends(require_tools),
    settings: Settings = Depends(get_settings),
    proxy: McpProxy = Depends(get_proxy),
) -> Response:
    policy = SERVER_POLICY if TOOLS_EXECUTE in account.permission_names else SERVER_VIEW_POLICY
    body = await _checked_body(request, policy)
    if isinstance(body, Response):
        return body
    return await proxy.forward(request, settings.mcp_server_url, account, body, target="mcp_server")
