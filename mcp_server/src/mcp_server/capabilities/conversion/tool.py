"""S/4HANA conversion pre-check tools."""

from __future__ import annotations

from mcp_server.capabilities.conversion.contract import SidRequest
from mcp_server.capabilities.conversion.domain import check_case_sensitivity_duplicates, get_scan_progress
from mcp_server.config import settings
from mcp_server.infra.sap_config import load_config
from mcp_server.server import mcp


@mcp.tool(description="Check the current progress of a duplicate key scan (while it's running)")
def get_scan_progress_tool(sid: str) -> str:
    return get_scan_progress(sid)


@mcp.tool(description=(
    "Proactive S/4HANA conversion pre-check for ECC systems running on Sybase ASE. "
    "Scans every UNIQUE index in the database (primary keys AND other unique constraints, "
    "including composite/multi-column ones) for duplicate key values — case-insensitive, "
    "since case differences are the most common cause but plain exact duplicates count too. "
    "Export to flat files never enforces uniqueness, so these duplicates won't cause export "
    "to fail — but the IMPORT phase into HANA fails when it tries to (re)build the unique "
    "index and finds colliding rows. Run this BEFORE starting the system conversion to catch "
    "it ahead of a failed import."
))
def check_case_sensitivity_duplicates_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return check_case_sensitivity_duplicates(SidRequest(sid=sid), config=config)
