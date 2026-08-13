"""SAP kernel update: the most architecturally unusual tool in this port.

Faithful port of apply_kernel_update (mcp_server.py) +
trigger_kernel_update_from_windows + its stop/start/wait helpers
(sap_operations.py). Full fidelity was the explicit choice for this
category, including two things every other tool in this port avoids:

1. This assumes the MCP SERVER PROCESS ITSELF runs on Windows with local
   filesystem access - it shells out to a local SAPCAR.exe to extract
   .SAR kernel files staged on a local/mapped drive, before SFTP-pushing
   the extracted files to the remote SAP host. Every other tool only
   needs network/SSH access to SAP hosts; this one needs to physically
   run on a specific machine with kernel files staged on it. Not
   redesigned to run remotely - preserved as-is per the fidelity
   decision.
2. Two email notifications - maintenance-started and completion - which
   never actually worked in the legacy code (the functions they called,
   send_email/build_kernel_update_email, never existed anywhere in the
   codebase; see infra/email.py's docstring for the full story). Real,
   working SMTP sending is wired in here for the first time - genuinely
   new functionality, not a port, per the explicit decision to build it.
   A failed send is logged into the returned report but never aborts the
   kernel update, matching the legacy code's evident intent (it wrapped
   both calls in a bare try/except that just printed and continued).

One more disclosed inconsistency, preserved rather than "fixed" since
it's not a crash: wait_for_green_blocking's DB branch connects via
_ssh_target(host, sap_cfg) with no user_field override, meaning it
defaults to sapadm - not hanaadm, unlike trigger_start_db's explicit
hanaadm+bash. Both exist in the legacy code as-is; not reconciled here.

This module also duplicates polling logic (wait-for-down, wait-for-green)
that capabilities/control/domain.py already has its own version of. This
mirrors a real duplication already present in the legacy codebase itself
(sap_operations.py has both a wait_for_pas_down/wait_for_ascs_down/
wait_for_aas_down family AND a separate wait_for_green_blocking) - kept
local to this file rather than refactored into a shared helper, both to
match that legacy structure and to avoid touching Control's
already-verified, already-tested polling code for this port.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import time
from datetime import datetime

from mcp_server.capabilities.kernel.contract import KernelUpdateRequest
from mcp_server.infra.email import build_kernel_update_email, build_maintenance_started_email, send_email
from mcp_server.infra.sap_config import AppConfig, SapServerConfig, find_sap_server
from mcp_server.infra.ssh import SSHClient, sftp_upload_dir

_ERROR_MARKERS = [
    "error: authentication failed", "authentication failed", "permission denied",
    "connection refused", "connection timed out", "could not resolve hostname",
    "no route to host", "host key verification failed", "operation timed out",
    "traceback (most recent call last)",
]


def _looks_like_remote_error(output: str) -> bool:
    if not output:
        return False
    lowered = output.lower()
    return any(marker in lowered for marker in _ERROR_MARKERS)


def _run_sap_ssh(host: str, user: str, password: str | None, command: str, shell: str = "csh") -> str:
    """String-return, stdout-else-stderr-fallback contract matching the
    legacy run_sap_ssh exactly - callers throughout this module parse the
    return value as a plain string (checking substrings like "BACKUP_OK",
    "GRAY"), not the (bool, stdout, stderr) tuple used elsewhere in this
    scaffold's infra."""
    try:
        with SSHClient(host, user, password=password) as ssh:
            result = ssh.run_login_shell(command, shell=shell)
        out = result.stdout.strip()
        err_clean = "\n".join(
            line for line in result.stderr.strip().splitlines()
            if not line.strip().startswith("[sudo]") and "password for" not in line.lower() and line.strip()
        )
        return out if out else err_clean
    except Exception as error:
        return f"❌ SAP SSH Error ({host}): {error}"


def _process_rows(output: str) -> list[list[str]]:
    rows = []
    for line in output.splitlines():
        line = line.strip()
        if line.lower().startswith("name,") or "," not in line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            rows.append(parts)
    return rows


def _get_sap_state(output: str) -> str:
    """Faithful port of sap_operations.py's get_sap_state - used by the
    DB/ASCS "already GREEN, skip start" checks. Note the slightly
    different parsing than _process_rows above (checks line doesn't
    START WITH "name" rather than "name," specifically, and doesn't
    require the 3-item length check before appending) - kept exactly as
    the original rather than unified, since they're used for different
    purposes (state summary vs per-process detail)."""
    if not output:
        return "DOWN"
    states = []
    for line in output.strip().splitlines():
        if "," in line and not line.startswith("name"):
            parts = line.split(",")
            if len(parts) >= 3:
                states.append(parts[2].strip().upper())
    if not states:
        return "UNKNOWN"
    if all(s == "GREEN" for s in states):
        return "GREEN"
    if any(s == "YELLOW" for s in states):
        return "YELLOW"
    if any(s in ("GRAY", "STOPPED") for s in states):
        return "DOWN"
    return "UNKNOWN"


def _wait_pas_and_aas_down(server: SapServerConfig, timeout: int = 120):
    pas_host, pas_nr = server.pashost, server.pas_nr
    aas_list = server.additional_app_servers
    start = time.time()

    while time.time() - start < timeout:
        pas_down = aas_down = True

        if pas_host and pas_nr:
            out = _run_sap_ssh(pas_host, server.sapadm or "", server.password, f"sapcontrol -nr {pas_nr} -function GetProcessList")
            for parts in _process_rows(out):
                if parts[2].upper() != "GRAY":
                    pas_down = False
                    yield f"⏳ PAS not down → {parts[2]} ({pas_host})\n"
                    break
            if pas_down:
                yield f"✅ PAS stopped ({pas_host})\n"

        for aas in aas_list:
            if not aas.host or not aas.instance:
                continue
            out = _run_sap_ssh(aas.host, server.sapadm or "", server.password, f"sapcontrol -nr {aas.instance} -function GetProcessList")
            inst_down = True
            for parts in _process_rows(out):
                if parts[2].upper() != "GRAY":
                    inst_down = False
                    yield f"⏳ AAS not down → {parts[2]} ({aas.host})\n"
                    break
            if inst_down:
                yield f"✅ AAS stopped ({aas.host})\n"
            else:
                aas_down = False

        if pas_down and aas_down:
            yield "✅ ALL APP SERVERS fully stopped\n"
            return True
        yield "⏳ Waiting for full shutdown...\n"
        time.sleep(5)

    yield "❌ Timeout waiting for app servers to stop\n"
    return False


def _wait_ascs_down(server: SapServerConfig, timeout: int = 60):
    start = time.time()
    while time.time() - start < timeout:
        out = _run_sap_ssh(server.ascshost or "", server.sapadm or "", server.password, f"sapcontrol -nr {server.ascs_nr} -function GetProcessList")
        if "GRAY" in out:
            yield "✅ ASCS fully stopped\n"
            return
        yield "⏳ Waiting ASCS down...\n"
        time.sleep(5)
    yield "❌ ASCS stop timeout\n"


def _wait_aas_down(server: SapServerConfig, timeout: int = 120):
    aas_list = server.additional_app_servers
    if not aas_list:
        yield "✅ No AAS configured — skipping\n"
        return

    start = time.time()
    while time.time() - start < timeout:
        all_down = True
        for aas in aas_list:
            if not aas.host or not aas.instance:
                continue
            out = _run_sap_ssh(aas.host, server.sapadm or "", server.password, f"sapcontrol -nr {aas.instance} -function GetProcessList")
            inst_down = True
            for parts in _process_rows(out):
                if parts[2].upper() != "GRAY":
                    inst_down = False
                    yield f"⏳ AAS not down → {parts[2]} ({aas.host})\n"
                    break
            if inst_down:
                yield f"✅ AAS stopped ({aas.host})\n"
            else:
                all_down = False
        if all_down:
            yield "✅ ALL AAS fully stopped\n"
            return
        yield "⏳ Waiting AAS shutdown...\n"
        time.sleep(5)
    yield "❌ Timeout waiting for AAS to stop\n"


def _wait_green_blocking(server: SapServerConfig, component: str, timeout: int = 300) -> tuple[bool, list[str]]:
    log: list[str] = []

    def _msg(m: str) -> None:
        log.append(m)

    if component == "PAS":
        targets = [(server.pashost, server.pas_nr, "PAS")]
        for aas in server.additional_app_servers:
            targets.append((aas.host, aas.instance, "AAS"))

        start = time.time()
        while time.time() - start < timeout:
            all_green = True
            for host, nr, label in targets:
                if not host or not nr:
                    continue
                out = _run_sap_ssh(host, server.sapadm or "", server.password, f"sapcontrol -nr {nr} -function GetProcessList")
                total = healthy = 0
                for parts in _process_rows(out):
                    total += 1
                    if parts[2].upper() in ("RED", "GRAY", "YELLOW", "UNKNOWN"):
                        _msg(f"⏳ {label} {host} not ready → {parts[2]}")
                        all_green = False
                        break
                    healthy += 1
                if total == 0 or not all_green:
                    all_green = False
            if all_green:
                _msg("✅ PAS/AAS fully GREEN")
                return True, log
            _msg(f"⏳ PAS waiting... ({int(time.time() - start)}s)")
            time.sleep(5)
        _msg("❌ PAS/AAS failed to become GREEN")
        return False, log

    host_map = {"DB": server.dbhost, "ASCS": server.ascshost}
    nr_map = {"DB": server.db_nr, "ASCS": server.ascs_nr}
    host, nr = host_map.get(component), nr_map.get(component)
    if not host or not nr:
        _msg(f"❌ Missing config for {component}")
        return False, log

    start = time.time()
    while time.time() - start < timeout:
        # Disclosed inconsistency, preserved: this uses sapadm (the
        # default), not hanaadm, even for the DB component - see module
        # docstring.
        out = _run_sap_ssh(host, server.sapadm or "", server.password, f"sapcontrol -nr {nr} -function GetProcessList")
        total = healthy = 0
        stuck = False
        for parts in _process_rows(out):
            total += 1
            if parts[2].upper() in ("RED", "GRAY", "YELLOW", "UNKNOWN"):
                _msg(f"⏳ {component} not ready → {parts[2]}")
                stuck = True
                break
            healthy += 1
        if total > 0 and healthy == total and not stuck:
            _msg(f"✅ {component} fully GREEN")
            return True, log
        _msg(f"⏳ {component} waiting... ({int(time.time() - start)}s)")
        time.sleep(5)
    _msg(f"❌ {component} failed to become GREEN")
    return False, log


def _parse_kernel_output(version_str: str | None) -> str | None:
    if not version_str:
        return None
    match = re.search(r"(\d{3})\s*\|\s*patch\s+number\s+(\d+)", version_str, re.IGNORECASE)
    if match:
        return f"{match.group(1)}.{match.group(2).zfill(2)}"
    match = re.search(r"\d{3}", version_str)
    return match.group(0) if match else None


def apply_kernel_update(request: KernelUpdateRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found in config.json"

    kernel_dir = server.kernel_dir
    if not kernel_dir:
        return (
            f"❌ VALIDATION FAILED for {sid}\n\n"
            f"Missing 'kernel_dir' in config.json\n"
            f"Add this to the sap_server entry for {sid}:\n"
            f'  "kernel_dir": "F:\\\\kernel_hana_linux",\n\n'
            f"Then stage .SAR files in that directory."
        )

    if not os.path.exists(kernel_dir):
        return f"❌ VALIDATION FAILED for {sid}\n\nKernel directory does not exist:\n  {kernel_dir}\n\nCreate this directory and stage the .SAR files."

    sar_files = sorted(glob.glob(os.path.join(kernel_dir, "*.SAR")))
    if not sar_files:
        return (
            f"❌ VALIDATION FAILED for {sid}\n\n"
            f"No .SAR kernel files found in:\n  {kernel_dir}\n\n"
            f"Expected files like:\n  SAPCAR_*.SAR\n  SAPEXE_*.SAR\n  SAPEXEDB_*.SAR\n\n"
            f"Stage the correct .SAR files and retry."
        )

    required_fields = {
        "pashost": server.pashost, "ascshost": server.ascshost, "dbhost": server.dbhost,
        "sapadm": server.sapadm, "hanaadm": server.hanaadm, "password": server.password,
        "pas_nr": server.pas_nr, "ascs_nr": server.ascs_nr, "db_nr": server.db_nr,
    }
    missing = [k for k, v in required_fields.items() if not v]
    if missing:
        return (
            f"❌ VALIDATION FAILED for {sid}\n\n"
            f"Missing required config fields: {', '.join(missing)}\n\n"
            f"Ensure all of these are set in config.json for {sid}:\n"
            f"  pashost, ascshost, dbhost, sapadm, hanaadm, password,\n  pas_nr, ascs_nr, db_nr"
        )

    log_lines = [
        f"\n{'=' * 70}\n", f"  Kernel Update for {sid.upper()}\n", f"{'=' * 70}\n\n",
        "✅ PRE-FLIGHT VALIDATION PASSED\n",
        f"  • Kernel directory: {kernel_dir}\n",
        f"  • SAR files found: {len(sar_files)}\n",
        "  • Config validated: All required fields present\n\n",
    ]

    try:
        for line in _trigger_kernel_update(server, kernel_dir, sar_files, config):
            log_lines.append(line)
    except Exception as error:
        log_lines.append(f"\n❌ Kernel update crashed: {error}\n")

    return "".join(log_lines)


def _trigger_kernel_update(server: SapServerConfig, kernel_dir: str, sar_files: list[str], config: AppConfig):
    sid = server.sid
    host, user, password = server.pashost or "", server.sapadm or "", server.password
    extract_dir = os.path.join(kernel_dir, "extract")
    kernel_results: list[dict[str, str]] = []

    yield "🚀 Starting Kernel Update...\n"
    yield f"📁 Using kernel directory: {kernel_dir}\n"

    yield "🔐 Verifying SSH connectivity to PAS host before taking the system down...\n"
    conn_check = _run_sap_ssh(host, user, password, "echo SSH_OK")
    if _looks_like_remote_error(conn_check) or "SSH_OK" not in conn_check:
        yield f"❌ Cannot reach {host} via SSH as {user} — aborting BEFORE stopping anything.\nRaw response: {conn_check!r}\n"
        return
    yield "✅ SSH connectivity confirmed\n"

    yield "🧹 Cleaning extract directory...\n"
    if os.path.exists(extract_dir):
        for item in os.listdir(extract_dir):
            p = os.path.join(extract_dir, item)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    os.makedirs(extract_dir, exist_ok=True)

    for sar in sar_files:
        yield f"📦 Extracting {os.path.basename(sar)}\n"
        result = subprocess.run([r"F:\kernel_hana_linux\SAPCAR.exe", "-xvf", sar], cwd=extract_dir, capture_output=True, text=True)
        yield f"OUTPUT:\n{result.stdout}\n{result.stderr}\n"

    old_kernel_version = _run_sap_ssh(host, user, password, f"sapcontrol -nr {server.pas_nr} -function GetVersionInfo | head -40")

    if config.email:
        try:
            send_email(
                config.email,
                subject="🛠 SAP Maintenance Activity Started",
                body_html=build_maintenance_started_email(sid, "stopped", [server.pashost or "", server.ascshost or ""]),
            )
            yield "📧 Maintenance-start email sent\n"
        except Exception as error:
            yield f"⚠️  Maintenance-start email failed: {error}\n"

    aas_list = server.additional_app_servers
    if aas_list:
        yield "🛑 Stopping AAS...\n"
        for aas in aas_list:
            _run_sap_ssh(aas.host, server.sapadm or "", password, f"sapcontrol -nr {aas.instance} -function Stop")
        aas_lines = []
        for line in _wait_aas_down(server):
            aas_lines.append(line)
            yield line
        if not aas_lines or not aas_lines[-1].strip().startswith("✅"):
            yield "❌ AAS did not confirm stopped — aborting kernel update (nothing changed on disk)\n"
            return

    yield "🛑 Stopping PAS...\n"
    _run_sap_ssh(host, user, password, f"sapcontrol -nr {server.pas_nr} -function Stop")
    pas_lines = []
    for line in _wait_pas_and_aas_down(server):
        pas_lines.append(line)
        yield line
    if not pas_lines or not pas_lines[-1].strip().startswith("✅"):
        yield "❌ PAS did not confirm stopped — aborting kernel update (nothing changed on disk)\n"
        return

    yield "🛑 Stopping ASCS...\n"
    _run_sap_ssh(server.ascshost or "", user, password, f"sapcontrol -nr {server.ascs_nr} -function Stop")
    ascs_lines = []
    for line in _wait_ascs_down(server):
        ascs_lines.append(line)
        yield line
    if not ascs_lines or not ascs_lines[-1].strip().startswith("✅"):
        yield "❌ ASCS did not confirm stopped — aborting kernel update (kernel files untouched). PAS/AAS are down; you can safely restart them since the kernel was never modified.\n"
        return

    yield "🧹 Cleaning old kernel backups...\n"
    cleanup_out = _run_sap_ssh(host, user, password, f"sh -c 'ls -d /sapmnt/{sid}/exe/uc/linuxx86_64_backup_* 2>/dev/null || true'")
    if _looks_like_remote_error(cleanup_out):
        yield f"❌ Could not reach {host} to list old kernel backups — aborting kernel update.\nRaw response: {cleanup_out!r}\nPAS/AAS/ASCS are already stopped — restart them manually once connectivity is restored.\n"
        return
    old_backups = [p.strip() for p in cleanup_out.splitlines() if p.strip()]
    if old_backups:
        for old in old_backups:
            yield f"🗑️  Removing {old}\n"
        rm_cmd = " ".join(f'"{p}"' for p in old_backups)
        _run_sap_ssh(host, user, password, f"rm -rf {rm_cmd}")
        yield f"✅ Removed {len(old_backups)} old backup(s)\n"
    else:
        yield "✅ No old backups found\n"

    backup_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"/sapmnt/{sid}/exe/uc/linuxx86_64_backup_{backup_ts}"
    yield f"💾 Backing up to {backup_dir}\n"
    out = _run_sap_ssh(host, user, password, f"cp -rp /sapmnt/{sid}/exe/uc/linuxx86_64 {backup_dir} && echo BACKUP_OK")
    if "BACKUP_OK" not in out:
        yield f"❌ Backup failed\nRaw response: {out!r}\nPAS/AAS/ASCS are already stopped — restart them manually once this is resolved.\n"
        return

    yield "📂 Copying new kernel files via SFTP...\n"
    try:
        uploaded = sftp_upload_dir(host, user, password or "", extract_dir, f"/sapmnt/{sid}/exe/uc/linuxx86_64")
        yield f"✅ Uploaded {uploaded} file(s)\n"
    except Exception as error:
        yield f"❌ SFTP upload failed: {error}\n"
        return

    _run_sap_ssh(host, user, password, f"chown -R {user}:sapsys /sapmnt/{sid}/exe/uc/linuxx86_64")
    _run_sap_ssh(host, user, password, f"chmod -R 755 /sapmnt/{sid}/exe/uc/linuxx86_64")

    yield "🔍 Checking DB state...\n"
    db_status = _run_sap_ssh(server.dbhost or "", server.hanaadm or "", password, f"sapcontrol -nr {server.db_nr} -function GetProcessList", shell="bash")
    if _get_sap_state(db_status) == "GREEN":
        yield "✅ DB already GREEN — skipping start\n"
    else:
        yield "🚀 DB not running — starting DB...\n"
        _run_sap_ssh(server.dbhost or "", server.hanaadm or "", password, f"sapcontrol -nr {server.db_nr} -function Start", shell="bash")
        ok, wait_log = _wait_green_blocking(server, "DB")
        for line in wait_log:
            yield line + "\n"
        if not ok:
            yield "❌ DB failed to become GREEN — aborting\n"
            return
        yield "✅ DB is GREEN\n"

    yield "🔍 Checking ASCS state...\n"
    ascs_status = _run_sap_ssh(server.ascshost or "", user, password, f"sapcontrol -nr {server.ascs_nr} -function GetProcessList")
    if _get_sap_state(ascs_status) == "GREEN":
        yield "✅ ASCS already GREEN — skipping start\n"
    else:
        yield "🚀 Starting ASCS...\n"
        _run_sap_ssh(server.ascshost or "", user, password, f"sapcontrol -nr {server.ascs_nr} -function Start")
        ok, wait_log = _wait_green_blocking(server, "ASCS")
        for line in wait_log:
            yield line + "\n"
        if not ok:
            yield "❌ ASCS failed to become GREEN — aborting\n"
            return
        yield "✅ ASCS is GREEN\n"

    yield "🚀 Starting PAS...\n"
    _run_sap_ssh(host, user, password, f"sapcontrol -nr {server.pas_nr} -function Start")
    ok, wait_log = _wait_green_blocking(server, "PAS")
    for line in wait_log:
        yield line + "\n"
    if not ok:
        yield "❌ PAS failed to become GREEN\n"
        return
    yield "✅ PAS is GREEN\n"

    if aas_list:
        yield "🚀 Starting AAS...\n"
        for aas in aas_list:
            _run_sap_ssh(aas.host, server.sapadm or "", password, f"sapcontrol -nr {aas.instance} -function Start")
        ok, wait_log = _wait_green_blocking(server, "PAS")  # PAS component check covers AAS hosts too
        for line in wait_log:
            yield line + "\n"
        if not ok:
            yield "⚠️  One or more AAS did not reach GREEN — check manually\n"
        else:
            yield "✅ AAS is GREEN\n"

    new_kernel_version = _run_sap_ssh(host, user, password, f"sapcontrol -nr {server.pas_nr} -function GetVersionInfo | head -40")
    old_kernel_parsed = _parse_kernel_output(old_kernel_version)
    new_kernel_parsed = _parse_kernel_output(new_kernel_version)
    kernel_results.append({"sid": sid, "host": host, "old_kernel": old_kernel_version, "new_kernel": new_kernel_version, "status": "SUCCESS"})

    if config.email:
        try:
            send_email(config.email, subject="✅ SAP Kernel Update Completed", body_html=build_kernel_update_email(kernel_results))
            yield "📧 Completion email sent\n"
        except Exception as error:
            yield f"⚠️  Completion email failed: {error}\n"

    yield f"✅ Old kernel: {old_kernel_parsed}\n"
    yield f"✅ New kernel: {new_kernel_parsed}\n"
    yield f"✅ Kernel updated for {sid}\n"
