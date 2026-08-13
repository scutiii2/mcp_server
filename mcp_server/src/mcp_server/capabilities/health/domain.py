"""SAP infrastructure health assessment + maintenance mode state.

The seven health-scoring helpers below (_health_icon through
_health_score) are faithful, verbatim-logic ports from mcp_server.py.

get_system_health is NOT a faithful port - it's a disclosed completion.
The legacy function has no bug in the usual sense; it's simply
INCOMPLETE. It does real SSH work to gather all eight health components
(CPU, memory, disk, SAP PAS, SAP ASCS, database, connectivity, kernel),
computes overall_status and health_score from all eight - then the
`lines` list it builds for display only ever appends the header, CPU,
and Memory sections. Disk/SAP-PAS/SAP-ASCS/Database/Connectivity/Kernel
are silently never formatted, and the function has no return statement
at all (confirmed via raw byte inspection, not a rendering artifact) -
it falls straight into the next tool's @mcp.tool() decorator. Every call
would do 6+ real SSH round-trips and then implicitly return None.

Reproducing that verbatim would mean shipping a tool that always returns
nothing after doing real work - not "full fidelity" to any actual
intended behavior, just an artifact of an unfinished edit. The six
missing display sections below are written fresh, following the exact
formatting convention the CPU/Memory sections already establish (══════
header bars, health-icon-prefixed titles, "Status : icon TEXT" trailer
lines) - not ported from source that doesn't exist, but not invented
from nothing either.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_server.capabilities.health.contract import MaintenanceModeRequest, SidRequest
from mcp_server.infra.sap_config import AppConfig, find_sap_server
from mcp_server.infra.ssh import run_command


def _health_icon(status: str | None) -> str:
    status = (status or "").upper()
    if status == "HEALTHY":
        return "✅"
    if status == "WARNING":
        return "⚠️"
    if status == "CRITICAL":
        return "❌"
    return "ℹ️"


def _parse_disk_health(df_output: str, warn_threshold: int = 80, crit_threshold: int = 90) -> tuple[str, list[dict]]:
    filesystems = []
    overall = "HEALTHY"

    for line in df_output.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("filesystem"):
            continue

        parts = line.split()
        if len(parts) < 6:
            continue

        fs, size, used, avail, use_pct_raw, mount = parts[:6]

        try:
            use_pct = int(use_pct_raw.replace("%", ""))
        except Exception:
            continue

        if use_pct >= crit_threshold:
            status = "CRITICAL"
            overall = "CRITICAL"
        elif use_pct >= warn_threshold:
            status = "WARNING"
            if overall != "CRITICAL":
                overall = "WARNING"
        else:
            status = "HEALTHY"

        filesystems.append({
            "filesystem": fs, "size": size, "used": used, "available": avail,
            "use_pct": use_pct, "mount": mount, "status": status,
        })

    return overall, filesystems


def _parse_memory_health(free_output: str, warn_threshold: int = 80, crit_threshold: int = 90) -> dict[str, Any]:
    result: dict[str, Any] = {
        "total_mb": 0, "used_mb": 0, "available_mb": 0, "used_pct": 0,
        "swap_total_mb": 0, "swap_used_mb": 0, "swap_used_pct": 0, "status": "UNKNOWN",
    }

    for line in free_output.splitlines():
        line = line.strip()

        if line.startswith("Mem:"):
            parts = line.split()
            if len(parts) >= 7:
                total, used, available = int(parts[1]), int(parts[2]), int(parts[6])
                result["total_mb"] = total
                result["used_mb"] = used
                result["available_mb"] = available
                result["used_pct"] = round((used / total) * 100, 2) if total else 0

        if line.startswith("Swap:"):
            parts = line.split()
            if len(parts) >= 3:
                swap_total, swap_used = int(parts[1]), int(parts[2])
                result["swap_total_mb"] = swap_total
                result["swap_used_mb"] = swap_used
                result["swap_used_pct"] = round((swap_used / swap_total) * 100, 2) if swap_total else 0

    used_pct = result["used_pct"]
    swap_pct = result["swap_used_pct"]

    if used_pct >= crit_threshold or swap_pct >= 50:
        result["status"] = "CRITICAL"
    elif used_pct >= warn_threshold or swap_pct >= 20:
        result["status"] = "WARNING"
    else:
        result["status"] = "HEALTHY"

    return result


def _parse_cpu_health(cpu_output: str, warn_threshold: int = 80, crit_threshold: int = 90) -> dict[str, Any]:
    result: dict[str, Any] = {"cpu_used_pct": 0, "load_avg": "", "cpu_cores": "", "status": "UNKNOWN"}

    for line in cpu_output.splitlines():
        line = line.strip()
        if line.startswith("CPU_USED="):
            try:
                result["cpu_used_pct"] = float(line.split("=", 1)[1].strip())
            except Exception:
                result["cpu_used_pct"] = 0
        elif line.startswith("LOAD_AVG="):
            result["load_avg"] = line.split("=", 1)[1].strip()
        elif line.startswith("CPU_CORES="):
            result["cpu_cores"] = line.split("=", 1)[1].strip()

    cpu_used = result["cpu_used_pct"]
    if cpu_used >= crit_threshold:
        result["status"] = "CRITICAL"
    elif cpu_used >= warn_threshold:
        result["status"] = "WARNING"
    else:
        result["status"] = "HEALTHY"

    return result


def _parse_sap_process_health(process_output: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "green": 0, "yellow": 0, "gray": 0, "red": 0,
        "raw": process_output.strip(), "status": "UNKNOWN",
    }

    upper = process_output.upper()
    result["green"] = upper.count("GREEN")
    result["yellow"] = upper.count("YELLOW")
    result["gray"] = upper.count("GRAY")
    result["red"] = upper.count("RED")

    if result["red"] > 0 or result["gray"] > 0:
        result["status"] = "CRITICAL"
    elif result["yellow"] > 0:
        result["status"] = "WARNING"
    elif result["green"] > 0:
        result["status"] = "HEALTHY"
    else:
        result["status"] = "UNKNOWN"

    return result


def _overall_status(component_statuses: list[str | None]) -> str:
    statuses = [s.upper() for s in component_statuses if s]

    if "CRITICAL" in statuses:
        return "CRITICAL"
    if "WARNING" in statuses:
        return "WARNING"
    if statuses and all(s == "HEALTHY" for s in statuses):
        return "HEALTHY"
    return "WARNING"


def _health_score(component_statuses: list[str | None]) -> int:
    scores = []
    for status in component_statuses:
        status = (status or "UNKNOWN").upper()
        if status == "HEALTHY":
            scores.append(100)
        elif status == "WARNING":
            scores.append(60)
        elif status == "CRITICAL":
            scores.append(20)
        else:
            scores.append(50)

    if not scores:
        return 0
    return round(sum(scores) / len(scores))


_CPU_CMD = r"""
CPU_IDLE=$(top -bn1 | awk -F',' '/Cpu\(s\)|%Cpu/ {for(i=1;i<=NF;i++){if($i ~ /id/){gsub(/[^0-9.]/,"",$i); print $i; exit}}}')
if [ -z "$CPU_IDLE" ]; then CPU_IDLE=0; fi
CPU_USED=$(awk "BEGIN {printf \"%.2f\", 100 - $CPU_IDLE}")
LOAD_AVG=$(awk '{print $1" "$2" "$3}' /proc/loadavg)
CPU_CORES=$(nproc 2>/dev/null || echo unknown)
echo "CPU_USED=$CPU_USED"
echo "LOAD_AVG=$LOAD_AVG"
echo "CPU_CORES=$CPU_CORES"
"""


def get_system_health(request: SidRequest, *, config: AppConfig) -> str:
    sid = (request.sid or "").strip().upper()
    if not sid:
        return "❌ Please provide SID. Example: get_system_health('E4G')"

    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found in config.json under sap_server."

    pashost, ascshost, dbhost = server.pashost or "", server.ascshost or "", server.dbhost or ""
    sapadm, hanaadm = server.sapadm or "", server.hanaadm or ""
    key, password = server.key, server.password
    pas_nr, ascs_nr, db_nr = server.pas_nr or "00", server.ascs_nr or "", server.db_nr or "00"

    assessment_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    components: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    success, cpu_out, cpu_err = run_command(pashost, sapadm, key=key, password=password, command=_CPU_CMD, timeout=30)
    if success:
        components["cpu"] = _parse_cpu_health(cpu_out)
    else:
        components["cpu"] = {"status": "UNKNOWN", "error": cpu_err or cpu_out}
        errors.append(f"CPU check failed: {cpu_err or cpu_out}")

    success, mem_out, mem_err = run_command(pashost, sapadm, key=key, password=password, command="free -m", timeout=30)
    if success:
        components["memory"] = _parse_memory_health(mem_out)
    else:
        components["memory"] = {"status": "UNKNOWN", "error": mem_err or mem_out}
        errors.append(f"Memory check failed: {mem_err or mem_out}")

    disk_cmd = "df -hP | egrep -v 'tmpfs|devtmpfs|overlay|Filesystem'"
    success, disk_out, disk_err = run_command(pashost, sapadm, key=key, password=password, command=disk_cmd, timeout=30)
    if success:
        disk_status, disk_items = _parse_disk_health(disk_out)
        components["disk"] = {"status": disk_status, "filesystems": disk_items}
    else:
        components["disk"] = {"status": "UNKNOWN", "error": disk_err or disk_out}
        errors.append(f"Disk check failed: {disk_err or disk_out}")

    sap_cmd = f"sapcontrol -nr {pas_nr} -function GetProcessList"
    success, sap_out, sap_err = run_command(pashost, sapadm, key=key, password=password, command=sap_cmd, timeout=45)
    if success:
        components["sap_pas"] = _parse_sap_process_health(sap_out)
    else:
        components["sap_pas"] = {"status": "UNKNOWN", "error": sap_err or sap_out}
        errors.append(f"SAP PAS process check failed: {sap_err or sap_out}")

    if ascshost and ascs_nr:
        ascs_cmd = f"sapcontrol -nr {ascs_nr} -function GetProcessList"
        success, ascs_out, ascs_err = run_command(ascshost, sapadm, key=key, password=password, command=ascs_cmd, timeout=45)
        if success:
            components["sap_ascs"] = _parse_sap_process_health(ascs_out)
        else:
            components["sap_ascs"] = {"status": "UNKNOWN", "error": ascs_err or ascs_out}
            errors.append(f"SAP ASCS process check failed: {ascs_err or ascs_out}")
    else:
        components["sap_ascs"] = {"status": "UNKNOWN", "error": "ASCS host or ASCS instance number not configured"}

    if dbhost:
        if hanaadm:
            db_cmd = f"sapcontrol -nr {db_nr} -function GetProcessList"
            success, db_out, db_err = run_command(dbhost, hanaadm, key=key, password=password, command=db_cmd, timeout=45)
            if success:
                components["database"] = _parse_sap_process_health(db_out)
            else:
                components["database"] = {"status": "UNKNOWN", "error": db_err or db_out}
                errors.append(f"DB sapcontrol check failed: {db_err or db_out}")
        else:
            db_cmd = "ps -ef | egrep -i 'hdbnameserver|hdbindexserver|dataserver|sqlsrvr' | grep -v grep | head -20"
            success, db_out, db_err = run_command(dbhost, sapadm, key=key, password=password, command=db_cmd, timeout=30)
            if success and db_out.strip():
                components["database"] = {"status": "HEALTHY", "raw": db_out.strip()}
            elif success:
                components["database"] = {"status": "WARNING", "raw": "No common DB process found using ps check"}
            else:
                components["database"] = {"status": "UNKNOWN", "error": db_err or db_out}
                errors.append(f"DB process check failed: {db_err or db_out}")
    else:
        components["database"] = {"status": "UNKNOWN", "error": "DB host not configured"}

    if dbhost:
        net_cmd = f"ping -c 2 -W 2 {dbhost} >/dev/null 2>&1 && echo OK || echo FAILED"
        success, net_out, net_err = run_command(pashost, sapadm, key=key, password=password, command=net_cmd, timeout=15)
        if success and "OK" in net_out:
            components["connectivity"] = {"status": "HEALTHY", "detail": f"{pashost} to {dbhost} reachable"}
        elif success:
            components["connectivity"] = {"status": "CRITICAL", "detail": f"{pashost} to {dbhost} ping failed"}
        else:
            components["connectivity"] = {"status": "UNKNOWN", "error": net_err or net_out}
            errors.append(f"Connectivity check failed: {net_err or net_out}")
    else:
        components["connectivity"] = {"status": "UNKNOWN", "error": "DB host not configured"}

    kernel_cmd = f"sapcontrol -nr {pas_nr} -function GetVersionInfo | head -40"
    success, kernel_out, kernel_err = run_command(pashost, sapadm, key=key, password=password, command=kernel_cmd, timeout=45)
    if success and kernel_out.strip():
        components["kernel"] = {"status": "HEALTHY", "raw": kernel_out.strip()}
    else:
        components["kernel"] = {"status": "UNKNOWN", "error": kernel_err or kernel_out}
        errors.append(f"Kernel check failed: {kernel_err or kernel_out}")

    status_list = [components.get(k, {}).get("status") for k in
                   ("cpu", "memory", "disk", "sap_pas", "sap_ascs", "database", "connectivity", "kernel")]
    overall = _overall_status(status_list)
    score = _health_score(status_list)

    lines = [
        f"🔍 {sid} Infrastructure Health Assessment", "",
        "══════════════════════════════════════", "🖥️ Server Information", "══════════════════════════════════════",
        f"SID              : {sid}",
        f"PAS Host         : {pashost or 'Not configured'}",
        f"ASCS Host        : {ascshost or 'Not configured'}",
        f"DB Host          : {dbhost or 'Not configured'}",
        f"Assessment Time  : {assessment_time}",
        "",
    ]

    cpu = components.get("cpu", {})
    lines += [
        "══════════════════════════════════════", f"{_health_icon(cpu.get('status'))} CPU Status", "══════════════════════════════════════",
        f"Current Usage    : {cpu.get('cpu_used_pct', 'NA')}%",
        f"Load Average     : {cpu.get('load_avg', 'NA')}",
        f"CPU Cores        : {cpu.get('cpu_cores', 'NA')}",
        f"Status           : {_health_icon(cpu.get('status'))} {cpu.get('status', 'UNKNOWN')}", "",
    ]

    mem = components.get("memory", {})
    lines += [
        "══════════════════════════════════════", f"{_health_icon(mem.get('status'))} Memory / Swap Status", "══════════════════════════════════════",
        f"Total Memory     : {mem.get('total_mb', 'NA')} MB",
        f"Used Memory      : {mem.get('used_mb', 'NA')} MB",
        f"Available Memory : {mem.get('available_mb', 'NA')} MB",
        f"Memory Usage     : {mem.get('used_pct', 'NA')}%",
        f"Swap Total       : {mem.get('swap_total_mb', 'NA')} MB",
        f"Swap Used        : {mem.get('swap_used_mb', 'NA')} MB",
        f"Swap Usage       : {mem.get('swap_used_pct', 'NA')}%",
        f"Status           : {_health_icon(mem.get('status'))} {mem.get('status', 'UNKNOWN')}", "",
    ]

    # ── Everything below this point is the disclosed completion - see
    # module docstring. Not present in the legacy source at all.
    disk = components.get("disk", {})
    lines += ["══════════════════════════════════════", f"{_health_icon(disk.get('status'))} Disk Status", "══════════════════════════════════════"]
    if disk.get("filesystems"):
        for fs in disk["filesystems"]:
            lines.append(
                f"  {fs['filesystem']:<20} {fs['size']:>6} {fs['used']:>6} {fs['available']:>6} "
                f"{fs['use_pct']:>4}% {fs['mount']:<15} {_health_icon(fs['status'])} {fs['status']}"
            )
    elif disk.get("error"):
        lines.append(f"  Error: {disk['error']}")
    lines.append(f"Status           : {_health_icon(disk.get('status'))} {disk.get('status', 'UNKNOWN')}")
    lines.append("")

    for label, key_name in (("SAP PAS", "sap_pas"), ("SAP ASCS", "sap_ascs"), ("Database", "database")):
        comp = components.get(key_name, {})
        lines += ["══════════════════════════════════════", f"{_health_icon(comp.get('status'))} {label} Status", "══════════════════════════════════════"]
        if "green" in comp:
            lines.append(f"Processes        : {comp.get('green', 0)}✅ {comp.get('yellow', 0)}⚠️ {comp.get('gray', 0)}⛔ {comp.get('red', 0)}❌")
        elif comp.get("raw"):
            lines.append(f"Detail           : {comp['raw']}")
        elif comp.get("error"):
            lines.append(f"Error            : {comp['error']}")
        lines.append(f"Status           : {_health_icon(comp.get('status'))} {comp.get('status', 'UNKNOWN')}")
        lines.append("")

    conn = components.get("connectivity", {})
    lines += ["══════════════════════════════════════", f"{_health_icon(conn.get('status'))} App-to-DB Connectivity", "══════════════════════════════════════"]
    lines.append(f"Detail           : {conn.get('detail') or conn.get('error', 'N/A')}")
    lines.append(f"Status           : {_health_icon(conn.get('status'))} {conn.get('status', 'UNKNOWN')}")
    lines.append("")

    kernel = components.get("kernel", {})
    lines += ["══════════════════════════════════════", f"{_health_icon(kernel.get('status'))} Kernel Version", "══════════════════════════════════════"]
    if kernel.get("raw"):
        lines.append(kernel["raw"])
    elif kernel.get("error"):
        lines.append(f"Error            : {kernel['error']}")
    lines.append(f"Status           : {_health_icon(kernel.get('status'))} {kernel.get('status', 'UNKNOWN')}")
    lines.append("")

    lines += [
        "══════════════════════════════════════", "📊 Overall Health", "══════════════════════════════════════",
        f"Overall Status   : {_health_icon(overall)} {overall}",
        f"Health Score     : {score}/100",
    ]
    if errors:
        lines.append("")
        lines.append("⚠️ Errors encountered during assessment:")
        for err in errors:
            lines.append(f"  • {err}")

    return "\n".join(lines)


def get_maintenance_status(*, maintenance_path: Path) -> str:
    try:
        with maintenance_path.open() as f:
            data = json.load(f)
        if not data:
            return "✅ No systems in maintenance mode."
        lines = ["Systems in maintenance mode:"]
        for sid, info in data.items():
            lines.append(f"  🛠 {sid.upper()} — since {info.get('since', 'unknown')}")
        return "\n".join(lines)
    except FileNotFoundError:
        return "✅ No systems in maintenance mode."
    except Exception as error:
        return f"❌ Error reading maintenance state: {error}"


def set_maintenance_mode(request: MaintenanceModeRequest, *, maintenance_path: Path) -> str:
    try:
        data: dict[str, Any] = {}
        if maintenance_path.exists():
            with maintenance_path.open() as f:
                data = json.load(f)

        key = request.sid.lower()
        if request.enable:
            data[key] = {"since": datetime.now().isoformat(timespec="seconds")}
            msg = f"🛠 Maintenance ENABLED for {request.sid.upper()}"
        else:
            data.pop(key, None)
            msg = f"✅ Maintenance DISABLED for {request.sid.upper()}"

        with maintenance_path.open("w") as f:
            json.dump(data, f, indent=2)
        return msg
    except Exception as error:
        return f"❌ Error updating maintenance state: {error}"
