"""SAP system control: pure business logic, no MCP or transport concerns.

This is the layer that actually knows what "stopping a SAP system" means.
It's testable with a fake/mocked SSHClient and has never heard of FastMCP -
compare to the legacy ``stop_sap_system`` tool, which mixed SID lookup, SSH
connection setup, and shell-command construction all inside the same
``@mcp.tool()``-decorated function.
"""

from __future__ import annotations

from mcp_server.capabilities.control.contract import StopSapRequest, StopSapResult
from mcp_server.infra.sap_config import AppConfig, find_sap_server
from mcp_server.infra.ssh import SSHClient


def stop_sap_system(request: StopSapRequest, *, config: AppConfig) -> StopSapResult:
    server = find_sap_server(request.sid, config)
    if server is None:
        return StopSapResult(
            sid=request.sid,
            success=False,
            message=f"No server configured for SID {request.sid}",
        )

    sidadm = f"{server.sid.lower()}adm"
    with SSHClient(server.host, server.user, key=server.key, password=server.password) as ssh:
        result = ssh.run(f"su - {sidadm} -c 'stopsap'")

    success = result.ok and "error" not in result.stdout.lower()
    message = result.stdout.strip()[-2000:] or result.stderr.strip()
    return StopSapResult(sid=request.sid, success=success, message=message)
