"""Human-friendly display titles for MCP tools.

MCP tool names are snake_case identifiers meant for machines
(``stop_sap_system_tool``) - not something you'd want as a page heading.
This lives on the Flask side, not the MCP server side, deliberately: newer
versions of the MCP spec/FastMCP may support a ``title`` field directly on
``@mcp.tool()``, but that's an assumption about an installed package
version this scaffold can't verify without the real package available.
This approach works regardless of what your installed ``mcp`` version
supports, and needs no changes to ``mcp_server`` at all.
"""

from __future__ import annotations

# Explicit overrides for tools whose auto-generated title wouldn't read
# well (acronyms, awkward capitalization, etc). Add an entry here as new
# tools are built if the auto-generated fallback below looks wrong -
# common culprits are SAP-specific acronyms (SAP, SID, ABAP, HANA, SSH).
_OVERRIDES: dict[str, str] = {
    "stop_sap_system_tool": "Stop SAP System",
    "start_sap_system_tool": "Start SAP System",
    "get_available_sids_tool": "Get Available SIDs",
    "list_sap_systems_tool": "List SAP Systems",
    "check_work_process_errors_tool": "Check Work Process Errors",
    "get_work_process_breakdown_tool": "Work Process Breakdown",
    "debug_raw_process_list_tool": "Debug Raw Process List",
    "get_sap_process_list_tool": "Get SAP Process List",
    "get_sap_process_status_tool": "Get SAP Process Status",
    "get_sap_system_health_tool": "Get SAP System Health",
    "get_kernel_version_tool": "Get Kernel Version",
    "check_disk_usage_tool": "Check Disk Usage",
    "find_largest_files_tool": "Find Largest Files",
    "check_cpu_usage_tool": "Check CPU Usage",
    "check_memory_usage_tool": "Check Memory Usage",
    "get_hana_status_tool": "Get HANA Status",
    "get_abap_dumps_tool": "Get ABAP Dumps",
    "analyze_latest_dump_tool": "Analyze Latest Dump",
    "analyze_abap_dump_tool": "Analyze ABAP Dump",
    "get_system_health_tool": "System Health Assessment",
    "get_maintenance_status_tool": "Get Maintenance Status",
    "set_maintenance_mode_tool": "Set Maintenance Mode",
    "get_job_failures_tool": "Get Job Failures",
    "get_job_log_tool": "Get Job Log",
    "reschedule_job_tool": "Reschedule Job",
    "get_long_running_jobs_tool": "Get Long-Running Jobs",
    "get_completed_jobs_tool": "Get Completed Jobs",
    "get_longest_completed_jobs_tool": "Get Longest Completed Jobs",
    "get_job_trend_analysis_tool": "Job Trend Analysis",
    "apply_kernel_update_tool": "Apply Kernel Update",
    "get_scan_progress_tool": "Get Scan Progress",
    "check_case_sensitivity_duplicates_tool": "Check Case-Sensitivity Duplicates",
}


def title_for(tool_name: str) -> str:
    if tool_name in _OVERRIDES:
        return _OVERRIDES[tool_name]
    name = tool_name[:-5] if tool_name.endswith("_tool") else tool_name
    return name.replace("_", " ").strip().title() or tool_name
