"""The browser's only way to ai_agent and mcp_server: agent listing and the
MCP proxy (Streamable HTTP: POST messages, GET event stream, DELETE session)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from src.config import Settings
from src.deps import get_settings, require_permission
from src.models import Account
from src.services.agent_directory import AgentDirectory
from src.services.mcp_policy import AGENT_POLICY, SERVER_POLICY, McpPolicy, PolicyViolation
from src.services.mcp_proxy import McpProxy
from src.services.permissions import CHAT_USE, TOOLS_USE

router = APIRouter(prefix="/api", tags=["mcp"])

MAX_BODY_BYTES = 1_000_000

require_chat = require_permission(CHAT_USE)
require_tools = require_permission(TOOLS_USE)

_PROXY_METHODS = ["GET", "POST", "DELETE"]


def get_agent_directory(settings: Settings = Depends(get_settings)) -> AgentDirectory:
    return AgentDirectory(settings.agents_registry_path)


def get_proxy(request: Request) -> McpProxy:
    return request.app.state.mcp_proxy


class AgentOut(BaseModel):
    # No URL: where the internal servers live stays server-side.
    id: str
    label: str


@router.get("/agents")
async def list_agents(
    _account: Account = Depends(require_chat),
    directory: AgentDirectory = Depends(get_agent_directory),
) -> list[AgentOut]:
    return [AgentOut(id=a.id, label=a.label) for a in await directory.all()]


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
    return await proxy.forward(request, agent.url, account, body)


@router.api_route("/mcp/server", methods=_PROXY_METHODS)
async def proxy_server(
    request: Request,
    account: Account = Depends(require_tools),
    settings: Settings = Depends(get_settings),
    proxy: McpProxy = Depends(get_proxy),
) -> Response:
    body = await _checked_body(request, SERVER_POLICY)
    if isinstance(body, Response):
        return body
    return await proxy.forward(request, settings.mcp_server_url, account, body)
