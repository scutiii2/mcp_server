"""Job-history resource - thin @mcp.resource() wrapper.

Distinct from a *tool*: this is read-only, browsable data addressed by a
URI template (``sap://job-history/{sid}``), not an action the model
deliberately invokes with arguments. A client can see the template shape
via resource discovery and construct a concrete URI itself, without a
tool-call round trip.

As with the ``title=`` question on tools earlier, I can't verify the
exact ``@mcp.resource()`` keyword arguments against your installed
``mcp==1.28.0`` in this sandbox - the URI-template-to-function-parameter
matching shown here (``{sid}`` in the URI maps to the ``sid`` parameter)
is FastMCP's documented, long-standing pattern, but confirm it behaves
as expected once you can actually run this.
"""

from __future__ import annotations

from mcp_server.config import settings
from mcp_server.infra.sap_config import load_config
from mcp_server.resources.job_history.contract import JobHistoryRequest
from mcp_server.resources.job_history.domain import get_job_history
from mcp_server.server import mcp


@mcp.resource("sap://job-history/{sid}")
def job_history_resource(sid: str) -> str:
    config = load_config(settings.config_path)
    result = get_job_history(JobHistoryRequest(sid=sid), config=config)
    return result.model_dump_json(indent=2)
