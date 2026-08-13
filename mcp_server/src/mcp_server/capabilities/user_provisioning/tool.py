"""SAP user creation tool - approval-gated (see domain.py's module
docstring for the full reasoning).

Only ``request_sap_user_creation_tool`` is exposed here. The execution
step deliberately has no ``@mcp.tool()`` anywhere - see
approval_routes.py, which is the only caller of
``execute_approved_user_creation``.
"""

from __future__ import annotations

from mcp_server.capabilities.user_provisioning.contract import RequestSapUserCreation
from mcp_server.capabilities.user_provisioning.domain import request_sap_user_creation
from mcp_server.config import settings
from mcp_server.infra.sap_config import load_config
from mcp_server.server import mcp


@mcp.tool(description=(
    "Request creation of a new SAP user account with role assignments. "
    "This does NOT create the account immediately - it validates the "
    "request (checks the user doesn't already exist, checks the "
    "requested roles actually exist on the target system) and sends an "
    "approval request to the configured approver(s). The account is only "
    "created after a human approves via the emailed link. Use this "
    "whenever someone asks to create, provision, or onboard a new SAP "
    "user - never invent or guess at role names, ask the user for them."
))
def request_sap_user_creation_tool(
    sid: str,
    user_id: str,
    first_name: str,
    last_name: str,
    email: str,
    requested_by: str,
    roles: list[str] | None = None,
    user_type: str = "A",
) -> str:
    config = load_config(settings.config_path)
    result = request_sap_user_creation(
        RequestSapUserCreation(
            sid=sid,
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            user_type=user_type,
            roles=roles or [],
            requested_by=requested_by,
        ),
        config=config,
        pending_db_path=settings.pending_requests_path,
        public_base_url=settings.public_base_url,
    )
    return result.message