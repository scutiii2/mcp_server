"""SAP monitoring: all 13 monitoring tools from the legacy codebase.

Faithful port of check_work_process_errors, get_work_process_breakdown
(with its 3-tier fallback parsing: comma-delimited ABAPGetWPTable, a
still-unimplemented alternate-format parser the legacy code also never
implemented - _parse_abap_work_process_table always returned None there
too, not a gap introduced here - and a DEFAULT.pfl profile-based
fallback), debug_raw_process_list, list_sap_systems, get_sap_process_list,
get_sap_process_status, get_sap_system_health, get_kernel_version (with
its sapcontrol -> disp+work fallback), check_disk_usage, find_largest_files,
check_cpu_usage, check_memory_usage, and get_hana_status, all from
mcp_server_copy/mcp_server.py. Every function returns a pre-formatted
report string, matching the original's style, rather than structured data
- that's what these tools actually produced.

One disclosed fix: the legacy get_sap_system_health indexed
sap_srv["pashost"] etc. directly with no None-check after the SID lookup
- an unhandled SID would crash with a raw TypeError instead of returning
a clean error message the way every other monitoring tool does. Fixed
here since it's clearly an oversight, not intended behavior; noted again
at that function's definition below.
"""

from __future__ import annotations

from datetime import datetime

from mcp_server.capabilities.monitoring.contract import DiskUsageRequest, FindLargestFilesRequest, SidRequest
from mcp_server.infra.sap_config import AppConfig, SapServerConfig, find_sap_server
from mcp_server.infra.ssh import run_command


def _run_ssh(server: SapServerConfig, command: str) -> tuple[bool, str, str]:
    """Maps a SapServerConfig onto the legacy _ssh() call shape: PAS host,
    sapadm user, key-then-password auth."""
    return run_command(
        server.pashost or server.host,
        server.sapadm or "",
        key=server.key,
        password=server.password,
        command=command,
    )


def list_sap_systems(config: AppConfig) -> str:
    if not config.sap_server:
        return "No SAP systems configured."
    lines = ["Configured SAP Systems:\n"]
    for server in config.sap_server:
        lines.append(
            f"  SID={server.sid or '?'}  "
            f"PAS={server.pashost or '?'}  "
            f"ASCS={server.ascshost or '?'}  "
            f"DB={server.dbhost or '?'}"
        )
    return "\n".join(lines)


def check_work_process_errors(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found in config."

    try:
        success, out, _err = _run_ssh(server, f"sapcontrol -nr {server.pas_nr or '00'} -function ABAPGetWPTable")

        if not success or not out.strip():
            return f"❌ No work process table returned for {sid}"

        data_lines = []
        for line in out.strip().split("\n"):
            line_s = line.strip()
            if "," not in line or "ABAPGetWPTable" in line or line_s in ("OK", "ERROR"):
                continue
            if "No," in line and "Typ," in line:
                continue
            first_field = line.split(",")[0].strip()
            if first_field.isdigit() or first_field == "":
                data_lines.append(line)

        if not data_lines:
            return f"⚠️  Could not parse work process table for {sid}"

        problematic: dict[str, list[dict]] = {"error": [], "stopped": [], "hold": [], "restart": []}
        all_statuses: dict[str, int] = {}

        for line in data_lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 4:
                continue
            try:
                wp_no = parts[0]
                wp_type = parts[1].upper() if len(parts) > 1 else None
                wp_pid = parts[2] if len(parts) > 2 else "?"
                wp_status = parts[3].upper() if len(parts) > 3 else "UNKNOWN"

                if not wp_type:
                    continue

                all_statuses[wp_status] = all_statuses.get(wp_status, 0) + 1

                process_info = {"no": wp_no, "type": wp_type, "pid": wp_pid, "status": wp_status}

                if wp_status == "ERROR":
                    problematic["error"].append(process_info)
                elif wp_status == "STOPPED":
                    problematic["stopped"].append(process_info)
                elif wp_status == "HOLD":
                    problematic["hold"].append(process_info)
                elif wp_status == "RESTART":
                    problematic["restart"].append(process_info)
            except (IndexError, ValueError):
                continue

        lines_out = [f"Work Process Health Check for {sid.upper()}\n", "=" * 70, ""]
        total_problems = sum(len(v) for v in problematic.values())

        if total_problems == 0:
            lines_out.append("✅ HEALTHY — All work processes running normally")
            lines_out.append("-" * 70)
            lines_out.append("")
            lines_out.append("Status distribution:")
            for status, count in sorted(all_statuses.items(), key=lambda x: -x[1]):
                lines_out.append(f"  {status:12} {count:3d} processes")
        else:
            lines_out.append(f"❌ PROBLEMS DETECTED — {total_problems} problematic process(es)")
            lines_out.append("-" * 70)
            lines_out.append("")

            labels = {"error": ("🔴 ERROR PROCESSES", "ERROR"), "stopped": ("⚫ STOPPED PROCESSES", "STOPPED"),
                      "hold": ("🟡 HELD PROCESSES", "HOLD"), "restart": ("🟠 RESTARTING PROCESSES", "RESTART")}
            for key, (label, _tag) in labels.items():
                if problematic[key]:
                    lines_out.append(f"{label} ({len(problematic[key])})")
                    lines_out.append("-" * 70)
                    for p in problematic[key]:
                        lines_out.append(f"  WP#{p['no']:>2}  Type: {p['type']:<3}  PID: {p['pid']:<6}  Status: {p['status']}")
                    lines_out.append("")

            lines_out.append("RECOMMENDED ACTIONS:")
            lines_out.append("-" * 70)
            if problematic["error"]:
                lines_out.append("  • ERROR processes must be restarted")
                lines_out.append("    sapcontrol -nr <nr> -function StartWP<type> <wpno>")
            if problematic["stopped"]:
                lines_out.append("  • STOPPED processes: verify why they're down")
                lines_out.append("    Check system logs and SAP monitoring")
            if problematic["hold"]:
                lines_out.append("  • HELD processes: resume with sapcontrol if needed")
                lines_out.append("    sapcontrol -nr <nr> -function ResumeWP")
            if problematic["restart"]:
                lines_out.append("  • RESTARTING: let the system complete restart")
            lines_out.append("")

        lines_out.append("=" * 70)
        lines_out.append(f"Checked at: {datetime.now().isoformat(timespec='seconds')}")
        return "\n".join(lines_out)

    except Exception as error:
        return f"❌ Error checking work process health: {error}"


def _parse_abap_comma_delimited(sid: str, out: str) -> str | None:
    """Parse comma-delimited ABAPGetWPTable (E4G/HANA format):
    No, Typ, Pid, Status, Reason, Start, Err, Sem, Cpu, Time, ..."""
    lines = out.strip().split("\n")
    if not lines:
        return None

    data_lines = []
    for line in lines:
        line_s = line.strip()
        if len(line_s) < 5 or "ABAPGetWPTable" in line or line_s in ("OK", "ERROR"):
            continue
        if "No," in line and "Typ," in line:
            continue
        if "," in line:
            first_field = line.split(",")[0].strip()
            if first_field.isdigit() or first_field == "":
                data_lines.append(line)

    if not data_lines:
        return None

    wp_types: dict[str, list[dict]] = {k: [] for k in ("dialog", "batch", "spool", "update", "enqueue", "gateway")}

    for line in data_lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            continue
        try:
            wp_type = parts[1].upper()
            wp_status_raw = parts[3].upper()
            if not wp_type:
                continue

            if wp_status_raw == "RUN":
                wp_status = "GREEN"
            elif wp_status_raw in ("WAIT", "HOLD", "RESTART"):
                wp_status = "YELLOW"
            elif wp_status_raw == "STOPPED":
                wp_status = "GRAY"
            else:
                wp_status = "YELLOW"

            process_info = {"type": wp_type, "status": wp_status, "raw_status": wp_status_raw}

            if wp_type == "DIA":
                wp_types["dialog"].append(process_info)
            elif wp_type == "BTC":
                wp_types["batch"].append(process_info)
            elif wp_type == "SPO":
                wp_types["spool"].append(process_info)
            elif wp_type in ("UPD", "UP2"):
                wp_types["update"].append(process_info)
            elif wp_type == "EN":
                wp_types["enqueue"].append(process_info)
            elif wp_type == "GW":
                wp_types["gateway"].append(process_info)
        except (IndexError, ValueError):
            continue

    total = sum(len(v) for v in wp_types.values())
    if total > 0:
        return _format_work_process_summary(sid, wp_types)
    return None


def _parse_abap_work_process_table(sid: str, out: str) -> str | None:
    """Fallback for other ABAPGetWPTable formats - unimplemented in the
    legacy code too (always returned None there); kept as an explicit
    no-op rather than silently dropped, so the fallback chain in
    get_work_process_breakdown reads the same as the original."""
    return None


def _get_work_processes_via_rz03(sid: str, server: SapServerConfig) -> str:
    """Query the DEFAULT.pfl profile for configured (not runtime) counts -
    last-resort fallback."""
    try:
        cmd = f"cat /usr/sap/{sid.upper()}/SYS/profile/DEFAULT.pfl 2>/dev/null"
        success, profile_out, _err = _run_ssh(server, cmd)

        if not success or not profile_out:
            return f"⚠️  Could not retrieve work process details for {sid}"

        wp_counts = {"dialog": 0, "batch": 0, "spool": 0, "update": 0, "enqueue": 0, "gateway": 0}

        for line in profile_out.split("\n"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.lower()
            try:
                val_int = int(val.strip())
            except ValueError:
                continue

            if "wp_no_dw" in key:
                wp_counts["dialog"] = val_int
            elif "wp_no_btc" in key:
                wp_counts["batch"] = val_int
            elif "wp_no_spo" in key:
                wp_counts["spool"] = val_int
            elif "wp_no_upd" in key:
                wp_counts["update"] = val_int
            elif "wp_no_en" in key:
                wp_counts["enqueue"] = val_int
            elif "wp_no_gw" in key:
                wp_counts["gateway"] = val_int

        total = sum(wp_counts.values())
        if total == 0:
            return f"⚠️  Could not parse profile for {sid}"

        return (
            f"Work Process Config for {sid.upper()}\n"
            f"  Dialog: {wp_counts['dialog']}, Batch: {wp_counts['batch']}, "
            f"Spool: {wp_counts['spool']}, Update: {wp_counts['update']}, "
            f"Enqueue: {wp_counts['enqueue']}, Gateway: {wp_counts['gateway']}"
        )
    except Exception as error:
        return f"⚠️  Error: {error}"


def _format_work_process_summary(sid: str, wp_types: dict[str, list[dict]]) -> str:
    lines = [f"Work Process Breakdown for {sid.upper()}\n", "=" * 70, ""]

    counts = {name: len(wp_types[name]) for name in ("dialog", "batch", "spool", "update", "enqueue", "gateway")}
    total = sum(counts.values())

    lines.append("📊 SUMMARY")
    lines.append("-" * 70)
    lines.append(f"  Dialog processes:   {counts['dialog']:2d}  (user interactive sessions)")
    lines.append(f"  Batch processes:    {counts['batch']:2d}  (background jobs)")
    lines.append(f"  Spool processes:    {counts['spool']:2d}  (print/PDF)")
    lines.append(f"  Update processes:   {counts['update']:2d}  (async updates)")
    lines.append(f"  Enqueue processes:  {counts['enqueue']:2d}  (lock management)")
    lines.append(f"  Gateway processes:  {counts['gateway']:2d}  (external)")
    lines.append("  ─────────────────────────────────────")
    lines.append(f"  TOTAL:              {total:2d}  processes")
    lines.append("")

    for name, procs in [
        ("DIALOG", wp_types["dialog"]), ("BATCH", wp_types["batch"]), ("SPOOL", wp_types["spool"]),
        ("UPDATE", wp_types["update"]), ("ENQUEUE", wp_types["enqueue"]), ("GATEWAY", wp_types["gateway"]),
    ]:
        if not procs:
            continue
        green = sum(1 for p in procs if p.get("status") == "GREEN")
        yellow = sum(1 for p in procs if p.get("status") == "YELLOW")
        gray = sum(1 for p in procs if p.get("status") == "GRAY")
        lines.append(f"  {name}: {green}✅ {yellow}🟡 {gray}⚫")

    return "\n".join(lines)


def get_work_process_breakdown(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found in config."

    try:
        success, out, _err = _run_ssh(server, f"sapcontrol -nr {server.pas_nr or '00'} -function ABAPGetWPTable")

        if not success or not out.strip():
            return f"❌ No work process table returned for {sid}"

        result = _parse_abap_comma_delimited(sid, out)
        if result:
            return result

        result = _parse_abap_work_process_table(sid, out)
        if result:
            return result

        return _get_work_processes_via_rz03(sid, server)

    except Exception as error:
        return f"❌ Error: {error}"


def get_sap_process_list(request: SidRequest, *, config: AppConfig) -> str:
    server = find_sap_server(request.sid, config)
    if not server:
        return f"❌ SID '{request.sid}' not found in config."
    try:
        success, out, err = _run_ssh(server, f"sapcontrol -nr {server.pas_nr or '00'} -function GetProcessList")
        return f"SAP Process List [{request.sid}]:\n{out}" if success else f"❌ {err}"
    except Exception as error:
        return f"❌ Error getting process list for {request.sid}: {error}"


def get_sap_process_status(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found"

    lines = [f"\nSAP SYSTEM STATUS [{sid}]\n", "=" * 70]

    systems = [
        ("PAS", server.pashost, server.sapadm, server.pas_nr),
        ("ASCS", server.ascshost, server.sapadm, server.ascs_nr),
        ("DB", server.dbhost, server.hanaadm, server.db_nr),
    ]

    for comp, host, user, inst_nr in systems:
        if not host or not inst_nr:
            continue
        lines.append(f"\n[{comp}]")
        success, out, err = run_command(
            host, user or "", key=server.key, password=server.password,
            command=f"sapcontrol -nr {inst_nr} -function GetProcessList",
        )
        lines.append(out if success else f"❌ {err}")

    return "\n".join(lines)


def get_sap_system_health(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    # Deliberate improvement over the legacy version, which indexed
    # sap_srv["pashost"] etc. directly with no None-check after
    # _find_sap_srv() - an unhandled SID lookup would crash with a raw
    # TypeError there instead of returning a clean error message like
    # every other monitoring tool does. Preserved everywhere else,
    # fixed here since it's clearly an oversight, not intended behavior.
    if not server:
        return f"❌ SID '{sid}' not found in config."

    components = [
        ("PAS", server.pashost, server.sapadm, server.pas_nr),
        ("ASCS", server.ascshost, server.sapadm, server.ascs_nr),
        ("DB", server.dbhost, server.hanaadm, server.db_nr),
    ]

    result = []
    for name, host, user, nr in components:
        success, out, _err = run_command(
            host or "", user or "", key=server.key, password=server.password,
            command=f"sapcontrol -nr {nr} -function GetProcessList",
        )

        if not success:
            result.append(f"{name}: ❌ UNREACHABLE")
            continue

        upper = out.upper()
        if "GREEN" in upper:
            result.append(f"{name}: ✅ GREEN")
        elif "YELLOW" in upper:
            result.append(f"{name}: ⚠️ YELLOW")
        elif "GRAY" in upper:
            result.append(f"{name}: ⛔ GRAY")
        else:
            result.append(f"{name}: ❓ UNKNOWN")

    return "\n".join(result)


def get_kernel_version(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found."
    try:
        success, out, _err = _run_ssh(server, f"sapcontrol -nr {server.pas_nr or '00'} -function GetVersionInfo")

        if success and out.strip() and "command not found" not in out.lower() and "no such file" not in out.lower():
            return f"Kernel Version [{sid}] (via sapcontrol):\n{out.strip()}"

        fallback_cmd = f"/sapmnt/{sid.upper()}/exe/uc/linuxx86_64/disp+work -V 2>&1 | head -5"
        _success2, fallback_out, _err2 = _run_ssh(server, fallback_cmd)

        if fallback_out.strip():
            return f"Kernel Version [{sid}] (via disp+work fallback):\n{fallback_out.strip()}"
        return (
            f"❌ Both sapcontrol and disp+work checks returned empty output for {sid}.\n"
            f"sapcontrol output: {out!r}\n"
            f"disp+work output: {fallback_out!r}"
        )
    except Exception as error:
        return f"❌ Error getting kernel version: {error}"


def check_disk_usage(request: DiskUsageRequest, *, config: AppConfig) -> str:
    sid, threshold = request.sid, request.threshold
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found."
    try:
        success, out, _err = _run_ssh(server, f"df -h | awk 'NR==1 || $5+0 >= {threshold}'")
        return (
            f"Disk Usage [{sid}] (≥{threshold}%):\n{out}"
            if out.strip()
            else f"✅ All filesystems below {threshold}% on {sid}"
        )
    except Exception as error:
        return f"❌ Error checking disk: {error}"


def find_largest_files(request: FindLargestFilesRequest, *, config: AppConfig) -> str:
    sid, mount_path, top_n = request.sid, request.mount_path, request.top_n
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found."
    try:
        cmd = f"find {mount_path} -xdev -type f -printf '%s %p\\n' | sort -rn | head -{top_n}"
        success, out, _err = _run_ssh(server, cmd)

        lines = []
        for line in out.splitlines():
            line = line.strip()
            if not line or " " not in line:
                continue
            size_str, _, path = line.partition(" ")
            try:
                size_bytes = int(size_str)
            except ValueError:
                continue
            size_mb = size_bytes / (1024 * 1024)
            lines.append(f"{size_mb:.2f} MB\t{path}")

        if not lines:
            return f"⚠️ No files found under {mount_path}, or the path doesn't exist / isn't readable.\nRaw output: {out!r}"

        return f"Largest Files in {mount_path} [{sid}] (top {top_n}):\n\n" + "\n".join(lines)
    except Exception as error:
        return f"❌ Error finding largest files in {mount_path} for {sid}: {error}"


def check_cpu_usage(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found."
    try:
        _success, top_out, _err = _run_ssh(server, "top -bn1 | head -5")
        _success, load_out, _err = _run_ssh(server, "cat /proc/loadavg")
        _success, mpstat_out, _err = _run_ssh(
            server, "mpstat -P ALL 1 1 2>/dev/null || echo '(mpstat not installed — per-core breakdown unavailable)'"
        )

        return (
            f"CPU Usage [{sid}]:\n\n"
            f"{top_out.strip()}\n\n"
            f"Load Average (1m / 5m / 15m):\n{load_out.strip()}\n\n"
            f"Per-Core Breakdown:\n{mpstat_out.strip()}"
        )
    except Exception as error:
        return f"❌ Error checking CPU usage for {sid}: {error}"


def check_memory_usage(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found."
    try:
        _success, mem_out, _err = _run_ssh(server, "free -h")
        _success, top_procs, _err = _run_ssh(server, "ps aux --sort=-%mem | head -6")

        return (
            f"Memory Usage [{sid}]:\n\n"
            f"{mem_out.strip()}\n\n"
            f"Top Memory-Consuming Processes:\n{top_procs.strip()}"
        )
    except Exception as error:
        return f"❌ Error checking memory usage for {sid}: {error}"


def get_hana_status(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found."
    try:
        _success, status, _err = run_command(
            server.dbhost or "", server.hanaadm or "", key=server.key, password=server.password,
            command=f"sapcontrol -nr {server.db_nr or '00'} -function GetProcessList",
        )
        _success, mem, _err = run_command(
            server.dbhost or "", server.hanaadm or "", key=server.key, password=server.password,
            command="free -h | grep Mem",
        )
        return f"HANA Status [{sid}]:\n{status}\nMemory:\n{mem}"
    except Exception as error:
        return f"❌ Error getting HANA status: {error}"


def debug_raw_process_list(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found in config."

    try:
        success, out, _err = _run_ssh(server, f"sapcontrol -nr {server.pas_nr or '00'} -function GetProcessList")

        if not success or not out.strip():
            return f"❌ No process list returned for {sid}"

        lines = out.strip().split("\n")

        debug_output = [
            f"RAW PROCESS LIST for {sid.upper()}",
            "=" * 80,
            f"Total lines: {len(lines)}",
            f"First line (likely header): {lines[0]!r}",
            "",
            "Full output with line numbers:",
            "-" * 80,
        ]

        for i, line in enumerate(lines, 1):
            debug_output.append(f"{i:3d}: {line!r}")

        debug_output.append("")
        debug_output.append("=" * 80)
        debug_output.append("ANALYSIS:")
        debug_output.append("-" * 80)

        if lines:
            first_line = lines[0]
            if "," in first_line:
                fields = first_line.split(",")
                debug_output.append("Delimiter: COMMA  (,)")
                debug_output.append(f"Number of fields in header: {len(fields)}")
                debug_output.append("Header fields:")
                for i, field in enumerate(fields):
                    debug_output.append(f"  [{i}] {field!r}")
            elif "\t" in first_line:
                fields = first_line.split("\t")
                debug_output.append("Delimiter: TAB")
                debug_output.append(f"Number of fields in header: {len(fields)}")
                debug_output.append("Header fields:")
                for i, field in enumerate(fields):
                    debug_output.append(f"  [{i}] {field!r}")
            elif " " in first_line:
                debug_output.append("Delimiter: SPACE (or multiple spaces)")
                debug_output.append(f"Raw line length: {len(first_line)} chars")

        if len(lines) > 1:
            debug_output.append("")
            debug_output.append("Second line (sample data):")
            debug_output.append(f"  {lines[1]!r}")

        return "\n".join(debug_output)

    except Exception as error:
        return f"❌ Error fetching raw process list for {sid}: {error}"
