"""SAP system control: multi-tier landscape orchestration via sapcontrol.

Restructured, faithful port of the legacy ``stop_one_server_blocking`` /
``start_one_server_blocking`` (``sap_operations.py``) and its process-state
parsing (``get_sap_state``). Confirmed against a real ``config.json``'s
actual field names (``dbhost``, ``ascshost``, ``pashost``, ``sapadm``,
``hanaadm``, ``db_nr``, ``ascs_nr``, ``pas_nr``, ``additional_app_servers``)
rather than assumed - this is NOT the simplified single-SSH-command version
this scaffold started with.

Deliberate simplification vs. the legacy version: the original ran this in
a background thread, writing live progress to a temp file that a Flask
route polled (the ``__LOG_FILE__`` streaming convention used throughout
the legacy app). An MCP tool call is a discrete request/response, not a
long-lived stream, so this blocks until the whole sequence completes and
returns the full accumulated log in one ``SapControlResult`` - the actual
SAP orchestration logic (tier order, idempotency checks, GREEN/DOWN
polling) is unchanged, only the "how progress gets back to the caller"
mechanism is simpler.

Stop order: additional app servers -> PAS -> ASCS -> DB (reverse of boot).
Start order: DB -> ASCS -> PAS -> additional app servers.
Every step first checks GetProcessList and skips if already in the target
state - idempotent, matching the original.
"""

from __future__ import annotations

import time

from mcp_server.capabilities.control.contract import (
    AvailableSidsResult,
    MultiSapControlResult,
    SapControlRequest,
    SapControlResult,
    SapSystemInfo,
)
from mcp_server.infra.sap_config import AppConfig, SapServerConfig, find_sap_server
from mcp_server.infra.ssh import SSHClient


_POLL_INTERVAL_SECONDS = 5
_DOWN_TIMEOUT_SECONDS = 180
_GREEN_TIMEOUT_SECONDS = 300


def get_available_sids(config: AppConfig) -> AvailableSidsResult:
    return AvailableSidsResult(
        systems=[
            SapSystemInfo(sid=server.sid.upper(), host=server.pashost or server.host)
            for server in config.sap_server
        ]
    )


def _parse_process_state(output: str) -> str:
    """Overall GREEN/YELLOW/DOWN/UNKNOWN state from a sapcontrol
    GetProcessList CSV-ish output - port of the legacy get_sap_state()."""
    if not output:
        return "DOWN"
    states: list[str] = []
    for line in output.strip().splitlines():
        if "," in line and not line.lower().startswith("name"):
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


def _get_process_list(host: str, user: str, password: str | None, nr: str, shell: str) -> str:
    with SSHClient(host, user, password=password) as ssh:
        return ssh.run_login_shell(f"sapcontrol -nr {nr} -function GetProcessList", shell=shell).stdout


def _sapcontrol_action(host: str, user: str, password: str | None, nr: str, action: str, shell: str) -> str:
    with SSHClient(host, user, password=password) as ssh:
        return ssh.run_login_shell(f"sapcontrol -nr {nr} -function {action}", shell=shell).stdout


def _wait_for_down(
    host: str, user: str, password: str | None, nr: str, shell: str, comp_name: str,
    timeout: int = _DOWN_TIMEOUT_SECONDS,
) -> list[str]:
    log = [f"⏳ Waiting {comp_name} DOWN on {host}...\n"]
    start = time.time()
    while time.time() - start < timeout:
        try:
            output = _get_process_list(host, user, password, nr, shell)
            state = _parse_process_state(output)
            if state not in ("GREEN", "YELLOW"):
                log.append(f"✅ {comp_name} fully stopped\n")
                return log
            log.append(f"⏳ {comp_name} still active → {state}\n")
        except Exception as error:
            log.append(f"❌ Error checking {comp_name}: {error}\n")
        time.sleep(_POLL_INTERVAL_SECONDS)
    log.append(f"❌ Timeout waiting for {comp_name} to stop\n")
    return log


def _wait_for_green(
    targets: list[tuple[str, str, str, str]],  # (host, nr, shell, comp_name)
    password: str | None,
    user_for: dict[str, str],  # comp_name -> user
    timeout: int = _GREEN_TIMEOUT_SECONDS,
) -> tuple[bool, list[str]]:
    """Block until every target in the group is GREEN. Grouping matters
    for the PAS+AAS case (all must be green together), same as the
    legacy wait_for_green_blocking's PAS branch; DB/ASCS pass a
    single-element group."""
    log: list[str] = []
    start = time.time()
    while time.time() - start < timeout:
        all_green = True
        for host, nr, shell, comp_name in targets:
            if not host or not nr:
                continue
            output = _get_process_list(host, user_for[comp_name], password, nr, shell)
            state = _parse_process_state(output)
            if state != "GREEN":
                log.append(f"⏳ {comp_name} {host} not ready → {state}\n")
                all_green = False
        if all_green:
            log.append("✅ fully GREEN\n")
            return True, log
        log.append(f"⏳ waiting... ({int(time.time() - start)}s)\n")
        time.sleep(_POLL_INTERVAL_SECONDS)
    log.append("❌ failed to become GREEN within timeout\n")
    return False, log


def _stop_one_sid(sid: str, server: SapServerConfig) -> SapControlResult:
    log = [f"\n🖥 Server: {sid}\n"]
    password = server.password

    for aas in server.additional_app_servers:
        if not aas.host or not aas.instance:
            continue
        output = _get_process_list(aas.host, server.sapadm or "", password, aas.instance, "csh")
        if _parse_process_state(output) != "DOWN":
            log.append(f"🛑 Stopping AAS {aas.host}...\n")
            _sapcontrol_action(aas.host, server.sapadm or "", password, aas.instance, "Stop", "csh")
            log.extend(_wait_for_down(aas.host, server.sapadm or "", password, aas.instance, "csh", f"AAS {aas.host}"))
        else:
            log.append(f"✅ AAS {aas.host} already stopped\n")

    if server.pashost and server.pas_nr:
        output = _get_process_list(server.pashost, server.sapadm or "", password, server.pas_nr, "csh")
        if _parse_process_state(output) != "DOWN":
            log.append("🛑 Stopping PAS...\n")
            _sapcontrol_action(server.pashost, server.sapadm or "", password, server.pas_nr, "Stop", "csh")
            log.extend(_wait_for_down(server.pashost, server.sapadm or "", password, server.pas_nr, "csh", "PAS"))
        else:
            log.append("✅ PAS already stopped\n")

    if server.ascshost and server.ascs_nr:
        output = _get_process_list(server.ascshost, server.sapadm or "", password, server.ascs_nr, "csh")
        if _parse_process_state(output) != "DOWN":
            log.append("🛑 Stopping ASCS...\n")
            _sapcontrol_action(server.ascshost, server.sapadm or "", password, server.ascs_nr, "Stop", "csh")
            log.extend(_wait_for_down(server.ascshost, server.sapadm or "", password, server.ascs_nr, "csh", "ASCS"))
        else:
            log.append("✅ ASCS already stopped\n")

    db_host = server.dbhost or server.host
    if db_host and server.db_nr:
        output = _get_process_list(db_host, server.hanaadm or "", password, server.db_nr, "bash")
        if _parse_process_state(output) != "DOWN":
            log.append("🛑 Stopping DB...\n")
            _sapcontrol_action(db_host, server.hanaadm or "", password, server.db_nr, "Stop", "bash")
            log.extend(_wait_for_down(db_host, server.hanaadm or "", password, server.db_nr, "bash", "DB"))
        else:
            log.append("✅ DB already stopped\n")

    message = "".join(log)
    success = "❌" not in message
    return SapControlResult(sid=sid, success=success, message=message)


def _start_one_sid(sid: str, server: SapServerConfig) -> SapControlResult:
    log = [f"\n🖥 Server: {sid}\n"]
    password = server.password

    db_host = server.dbhost or server.host
    if db_host and server.db_nr:
        output = _get_process_list(db_host, server.hanaadm or "", password, server.db_nr, "bash")
        if _parse_process_state(output) != "GREEN":
            log.append("🚀 Starting DB...\n")
            _sapcontrol_action(db_host, server.hanaadm or "", password, server.db_nr, "Start", "bash")
            ok, wait_log = _wait_for_green(
                [(db_host, server.db_nr, "bash", "DB")], password, {"DB": server.hanaadm or ""}
            )
            log.extend(wait_log)
            if not ok:
                log.append("❌ DB failed\n")
                return SapControlResult(sid=sid, success=False, message="".join(log))
        else:
            log.append("✅ DB already GREEN\n")

    if server.ascshost and server.ascs_nr:
        output = _get_process_list(server.ascshost, server.sapadm or "", password, server.ascs_nr, "csh")
        if _parse_process_state(output) != "GREEN":
            log.append("🚀 Starting ASCS...\n")
            _sapcontrol_action(server.ascshost, server.sapadm or "", password, server.ascs_nr, "Start", "csh")
            ok, wait_log = _wait_for_green(
                [(server.ascshost, server.ascs_nr, "csh", "ASCS")], password, {"ASCS": server.sapadm or ""}
            )
            log.extend(wait_log)
            if not ok:
                log.append("❌ ASCS failed\n")
                return SapControlResult(sid=sid, success=False, message="".join(log))
        else:
            log.append("✅ ASCS already GREEN\n")

    pas_targets: list[tuple[str, str, str, str]] = []
    user_for: dict[str, str] = {}
    if server.pashost and server.pas_nr:
        pas_targets.append((server.pashost, server.pas_nr, "csh", "PAS"))
        user_for["PAS"] = server.sapadm or ""
    for aas in server.additional_app_servers:
        if aas.host and aas.instance:
            pas_targets.append((aas.host, aas.instance, "csh", f"AAS {aas.host}"))
            user_for[f"AAS {aas.host}"] = server.sapadm or ""

    if server.pashost and server.pas_nr:
        output = _get_process_list(server.pashost, server.sapadm or "", password, server.pas_nr, "csh")
        if _parse_process_state(output) != "GREEN":
            log.append("🚀 Starting PAS...\n")
            _sapcontrol_action(server.pashost, server.sapadm or "", password, server.pas_nr, "Start", "csh")
            ok, wait_log = _wait_for_green(pas_targets, password, user_for)
            log.extend(wait_log)
            if not ok:
                log.append("❌ PAS failed\n")
                return SapControlResult(sid=sid, success=False, message="".join(log))
        else:
            log.append("✅ PAS already GREEN\n")

        for aas in server.additional_app_servers:
            if not aas.host or not aas.instance:
                continue
            output = _get_process_list(aas.host, server.sapadm or "", password, aas.instance, "csh")
            if _parse_process_state(output) != "GREEN":
                log.append(f"🚀 Starting AAS {aas.host}...\n")
                _sapcontrol_action(aas.host, server.sapadm or "", password, aas.instance, "Start", "csh")
                _, wait_log = _wait_for_green(
                    [(aas.host, aas.instance, "csh", f"AAS {aas.host}")], password, {f"AAS {aas.host}": server.sapadm or ""}
                )
                log.extend(wait_log)
            else:
                log.append(f"✅ AAS {aas.host} already GREEN\n")

    log.append("✅ SAP fully started\n")
    return SapControlResult(sid=sid, success=True, message="".join(log))


def stop_sap_system(request: SapControlRequest, *, config: AppConfig) -> MultiSapControlResult:
    sid_list = [s.strip().upper() for s in request.sid.replace("|", ",").replace(";", ",").split(",") if s.strip()]
    results = []
    for sid in sid_list:
        server = find_sap_server(sid, config)
        if server is None:
            results.append(SapControlResult(sid=sid, success=False, message=f"No server configured for SID {sid}"))
            continue
        results.append(_stop_one_sid(sid, server))
    return MultiSapControlResult(results=results)


def start_sap_system(request: SapControlRequest, *, config: AppConfig) -> MultiSapControlResult:
    sid_list = [s.strip().upper() for s in request.sid.replace("|", ",").replace(";", ",").split(",") if s.strip()]
    results = []
    for sid in sid_list:
        server = find_sap_server(sid, config)
        if server is None:
            results.append(SapControlResult(sid=sid, success=False, message=f"No server configured for SID {sid}"))
            continue
        results.append(_start_one_sid(sid, server))
    return MultiSapControlResult(results=results)
