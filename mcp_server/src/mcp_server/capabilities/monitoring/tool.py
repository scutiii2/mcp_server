"""SAP monitoring tools - all 13 from the legacy codebase.

Each function here is intentionally a few lines: load config, call the
domain function, return its result. If a tool needs more logic than
that, the logic belongs in ``domain/``, not here.
"""

from __future__ import annotations

from mcp_server.capabilities.monitoring.contract import DiskUsageRequest, FindLargestFilesRequest, SidRequest
from mcp_server.capabilities.monitoring.domain import (
    check_cpu_usage,
    check_disk_usage,
    check_memory_usage,
    check_work_process_errors,
    debug_raw_process_list,
    find_largest_files,
    get_hana_status,
    get_kernel_version,
    get_sap_process_list,
    get_sap_process_status,
    get_sap_system_health,
    get_work_process_breakdown,
    list_sap_systems,
)
from mcp_server.config import settings
from mcp_server.infra.sap_config import load_config
from mcp_server.server import mcp


@mcp.tool(description="List all SAP systems configured in the monitoring platform.")
def list_sap_systems_tool() -> str:
    config = load_config(settings.config_path)
    return list_sap_systems(config)


@mcp.tool(description=(
    "Check for SAP work processes in ERROR, STOPPED, or other problematic states. "
    "Scans all work processes and reports any that are not running normally. "
    "Useful for monitoring system health and identifying stuck or failed processes."
))
def check_work_process_errors_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return check_work_process_errors(SidRequest(sid=sid), config=config)


@mcp.tool(description=(
    "Get detailed work process breakdown for a SAP system. "
    "Queries the actual ABAP work process table using sapcontrol ABAPGetWPTable. "
    "Returns process count by type: dialog, batch, spool, update, enqueue, gateway. "
    "Shows current status for each process type."
))
def get_work_process_breakdown_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return get_work_process_breakdown(SidRequest(sid=sid), config=config)


@mcp.tool(description=(
    "DEBUG: Fetch and display the RAW unprocessed process list for a SAP system. "
    "Use this to diagnose format issues when get_work_process_breakdown_tool() fails "
    "with an 'unexpected format' error. Shows exactly what sapcontrol returns."
))
def debug_raw_process_list_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return debug_raw_process_list(SidRequest(sid=sid), config=config)


@mcp.tool(description="Get the current process list for a SAP system using sapcontrol. Returns GREEN/YELLOW/GRAY status for each process.")
def get_sap_process_list_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return get_sap_process_list(SidRequest(sid=sid), config=config)


@mcp.tool(description="Shows only SAP process status (PAS, ASCS, DB). Does not include CPU, memory, disk, OS, kernel or connectivity information.")
def get_sap_process_status_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return get_sap_process_status(SidRequest(sid=sid), config=config)


@mcp.tool(description="Show overall SAP system instance status (PAS/ASCS/DB GREEN/YELLOW/GRAY summary).")
def get_sap_system_health_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return get_sap_system_health(SidRequest(sid=sid), config=config)


@mcp.tool(description="Get the current SAP kernel version.")
def get_kernel_version_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return get_kernel_version(SidRequest(sid=sid), config=config)


@mcp.tool(description="Check disk usage on a SAP host. Returns filesystems at or above the given threshold percentage.")
def check_disk_usage_tool(sid: str, threshold: int = 80) -> str:
    config = load_config(settings.config_path)
    return check_disk_usage(DiskUsageRequest(sid=sid, threshold=threshold), config=config)


@mcp.tool(description=(
    "Find the largest individual files under a given mount point or directory on a SAP host. "
    "Use this after check_disk_usage_tool flags a filesystem as full or near-full, to identify "
    "exactly what is consuming the space. Pass the 'Mounted on' path returned by check_disk_usage_tool as mount_path."
))
def find_largest_files_tool(sid: str, mount_path: str, top_n: int = 10) -> str:
    config = load_config(settings.config_path)
    return find_largest_files(FindLargestFilesRequest(sid=sid, mount_path=mount_path, top_n=top_n), config=config)


@mcp.tool(description="Check current CPU usage and load average on a SAP host. Returns overall CPU utilisation, per-core breakdown (if available), and system load averages.")
def check_cpu_usage_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return check_cpu_usage(SidRequest(sid=sid), config=config)


@mcp.tool(description=(
    "Check current OS-level memory (RAM) usage on a SAP host. Returns total/used/free/available "
    "memory and top memory-consuming processes. This is OS memory - for HANA-specific memory, use get_hana_status_tool."
))
def check_memory_usage_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return check_memory_usage(SidRequest(sid=sid), config=config)


@mcp.tool(description="Check HANA database status and resource usage for a SAP system.")
def get_hana_status_tool(sid: str) -> str:
    config = load_config(settings.config_path)
    return get_hana_status(SidRequest(sid=sid), config=config)
