"""/api/admin/agents: create, edit and remove ai_agent's agent files.

Needs agents.manage. ai_agent validates and stores the files; its supervisor
starts, restarts or stops the agent within a few seconds, so a changed agent
shows as running/offline on GET /api/agents shortly after. Every change is
written to the activity log.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from pydantic import BaseModel, Field

from src.deps import get_log_writer, require_permission
from src.models import Account
from src.services.agent_admin import AgentAdmin, AgentAdminRefused, AgentAdminUnavailable
from src.services.log_service import LogWriter
from src.services.permissions import AGENTS_MANAGE

router = APIRouter(prefix="/api/admin/agents", tags=["agent-admin"])
# Not under /api/admin/agents: an agent id such as "prompts" would collide with these paths.
prompts_router = APIRouter(prefix="/api/admin", tags=["agent-admin"])

require_agents_manage = require_permission(AGENTS_MANAGE)

AGENT_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"


def get_agent_admin(request: Request) -> AgentAdmin:
    return AgentAdmin(
        request.app.state.upstream, request.app.state.agent_directory,
        request.app.state.internal_token, request.app.state.traffic,
    )


async def _call(awaitable) -> Any:
    try:
        return await awaitable
    except AgentAdminUnavailable as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "ai_agent is unreachable") from error
    except AgentAdminRefused as error:
        code = error.status if error.status in (404, 409) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, str(error)) from error


class CreateAgentIn(BaseModel):
    id: str = Field(pattern=AGENT_ID_PATTERN)
    config: dict[str, Any]


class UpdateAgentIn(BaseModel):
    config: dict[str, Any]


@router.get("/gateways")
async def gateways(account: Account = Depends(require_agents_manage), admin: AgentAdmin = Depends(get_agent_admin)) -> Any:
    """Providers and the gateways each offers, for the pickers."""
    return {"providers": await _call(admin.gateways(account))}


@router.get("")
async def list_agent_files(
    account: Account = Depends(require_agents_manage), admin: AgentAdmin = Depends(get_agent_admin)
) -> Any:
    """Every agent file: `{id, ...the file's fields}`; a broken file carries `error`."""
    return {"agents": await _call(admin.list(account))}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: CreateAgentIn,
    account: Account = Depends(require_agents_manage),
    admin: AgentAdmin = Depends(get_agent_admin),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    created = await _call(admin.create(account, body.id, body.config))
    await logs.action(account, "agents.create", f"Created agent '{body.id}'")
    return created


@router.put("/{agent_id}")
async def update_agent(
    body: UpdateAgentIn,
    agent_id: str = Path(pattern=AGENT_ID_PATTERN),
    account: Account = Depends(require_agents_manage),
    admin: AgentAdmin = Depends(get_agent_admin),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    updated = await _call(admin.update(account, agent_id, body.config))
    await logs.action(account, "agents.update", f"Updated agent '{agent_id}'")
    return updated


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str = Path(pattern=AGENT_ID_PATTERN),
    account: Account = Depends(require_agents_manage),
    admin: AgentAdmin = Depends(get_agent_admin),
    logs: LogWriter = Depends(get_log_writer),
) -> Response:
    await _call(admin.delete(account, agent_id))
    await logs.action(account, "agents.delete", f"Deleted agent '{agent_id}'")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PreviewIn(BaseModel):
    id: str = Field(pattern=AGENT_ID_PATTERN)
    config: dict[str, Any]
    caveman: bool = False


@prompts_router.get("/agent-prompts")
async def get_prompts(account: Account = Depends(require_agents_manage), admin: AgentAdmin = Depends(get_agent_admin)) -> Any:
    """The prompt texts every agent shares: `{values, defaults, overridden}`."""
    return await _call(admin.prompts(account))


@prompts_router.put("/agent-prompts")
async def set_prompts(
    changes: dict[str, str | None],
    account: Account = Depends(require_agents_manage),
    admin: AgentAdmin = Depends(get_agent_admin),
    logs: LogWriter = Depends(get_log_writer),
) -> Any:
    """Body `{name: text | null}`; null or blank resets a text. ai_agent restarts every agent to apply it."""
    result = await _call(admin.set_prompts(account, changes))
    await logs.action(account, "agents.prompts", f"Changed shared agent prompts ({', '.join(sorted(changes)) or 'none'})")
    return result


@prompts_router.post("/agent-prompt-preview")
async def preview_prompt(
    body: PreviewIn, account: Account = Depends(require_agents_manage), admin: AgentAdmin = Depends(get_agent_admin)
) -> Any:
    """The system prompt a draft agent file would get: `{prompt}`."""
    return {"prompt": await _call(admin.preview(account, body.id, body.config, body.caveman))}
