"""S/4HANA conversion pre-checks: case-sensitivity duplicate key scan.

Faithful port of check_case_sensitivity_duplicates, get_scan_progress,
phase_2_main/phase_2_batched_sequential/phase_2_batched_parallel, and the
SQL-building/output-parsing helpers (_escape_table_name,
_build_sp_helpindex_batch, _parse_table_list, _parse_sp_helpindex_batch,
_build_index_dup_check_sql, _parse_dup_output, _isql_failed) from
mcp_server.py/sap_utils.py. Uses isql over SSH against Sybase/ASE - a CLI
tool, not a real DB driver, matching the legacy approach exactly.

One disclosed, deliberate simplification: the legacy
check_case_sensitivity_duplicates wrapped its entire body in a
``DualStream`` class that monkey-patches ``sys.stdout``/``sys.stderr`` to
mirror every ``print()`` call into a buffer, then returned
``captured_output + "\\n" + final_result`` - meaning the tool's actual
response was prefixed with every single debug line from a scan that can
run for many minutes across hundreds of SSH round-trips (the legacy code
even has literal "[EMERGENCY-1]" through "[EMERGENCY-4]" debug markers
still in place, next to a comment reading "ALL EXISTING CODE (from your
function)" - this reads as leftover incident-debugging scaffolding, not
deliberate design). Globally redirecting sys.stdout/sys.stderr is also
genuinely unsafe in a server process that may be mid-flight on other
requests concurrently. This port keeps ``print()`` calls for local
console visibility during a long scan, but the tool's actual return
value is the clean final report only - not prefixed with captured debug
output.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime
from queue import Queue
from threading import Lock, Thread

from mcp_server.capabilities.conversion.contract import SidRequest
from mcp_server.infra.sap_config import AppConfig, find_sap_server
from mcp_server.infra.ssh import run_command, sftp_write_file

DUP_CHECK_BATCH_SIZE = 15
DUP_CHECK_ISQL_TIMEOUT = 180
DUP_CHECK_MAX_RETRIES = 3
DUP_CHECK_PARALLEL_WORKERS = 8
DUP_CHECK_USE_PARALLEL = True

_FIND_TABLES_WITH_UNIQUE_IDX_SQL = """\
SELECT DISTINCT o.name
FROM sysobjects o, sysindexes i
WHERE o.id = i.id
  AND o.type = 'U'
  AND i.status & 2 = 2
ORDER BY o.name
go
"""


def _run_isql_ssh(host: str, user: str, key: str | None, password: str | None, command: str, timeout: int = 30) -> tuple[bool, str, str]:
    return run_command(host, user, key=key, password=password, command=command, timeout=timeout)


def _escape_table_name(table_name: str) -> str:
    if not table_name or not isinstance(table_name, str):
        return "[unknown]"
    table_name = table_name.strip()
    if table_name.startswith("[") and table_name.endswith("]"):
        return table_name
    if "." in table_name:
        parts = table_name.split(".", 1)
        schema = parts[0].strip().strip("[]")
        table = parts[1].strip().strip("[]")
        return f"[{schema}].[{table}]"
    table_name = table_name.strip("[]")
    return f"[{table_name}]"


def _build_sp_helpindex_batch(tables: list[str]) -> str:
    chunks = []
    for table in tables:
        if not table or not isinstance(table, str):
            continue
        table = table.strip()
        if ";" in table or "--" in table or "/*" in table:
            continue
        escaped = _escape_table_name(table)
        chunks.append(f"PRINT '### TABLE: {table} ###'\ngo\nsp_helpindex {escaped}\ngo\n")
    return "\n".join(chunks) if chunks else ""


def _parse_table_list(raw: str) -> list[str]:
    tables = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("-") or line.lower() in ("name", "row_count") or "row(s)" in line.lower():
            continue
        if "  " in line and len(line.split()) > 2:
            continue
        fields = line.split()
        if not fields:
            continue
        table_name = fields[0]
        if any(char in table_name for char in [";", "--", "/*", "*/"]):
            continue
        if len(table_name) > 128:
            continue
        tables.append(table_name)
    return tables


def _parse_sp_helpindex_batch(raw: str) -> dict[str, list[str]]:
    indexes: dict[str, list[str]] = {}
    current_table = None

    for line in raw.splitlines():
        stripped = line.strip()
        marker = re.match(r"### TABLE: (.+?) ###", stripped)
        if marker:
            current_table = marker.group(1)
            continue
        if not current_table or not stripped:
            continue

        low = stripped.lower()
        if (low.startswith("index_name") or low.startswith("no defined") or low.startswith("no indexes")
                or "error" in low or "msg " in low or re.match(r"^-+(\s+-+)*$", stripped)):
            continue

        parts = re.split(r"\s{2,}", stripped)
        if len(parts) < 3:
            parts = stripped.split()
            if len(parts) < 3:
                continue

        try:
            idx_name = parts[0]
            idx_desc = parts[1] if len(parts) > 1 else ""
            idx_keys = parts[-1] if len(parts) > 2 else ""
            if "unique" not in idx_desc.lower():
                continue
            cols = [c.strip() for c in idx_keys.split(",") if c.strip()]
            if cols:
                indexes[f"{current_table}.{idx_name}"] = cols
        except (IndexError, ValueError):
            continue

    return indexes


def _build_index_dup_check_sql(indexes: dict[str, list[str]]) -> str:
    chunks = []
    for idx_name, cols in indexes.items():
        if not cols:
            continue
        try:
            parts = idx_name.rsplit(".", 1)
            if len(parts) != 2:
                continue
            table_name, index_name = parts
            escaped_cols = [f"[{col}]" for col in cols]
            key_expr = " + '||' + ".join(f"ISNULL(CONVERT(VARCHAR(8000), UPPER({col})), 'NULL')" for col in escaped_cols)
            group_by_expr = ", ".join(escaped_cols)
            sql = f"""
PRINT '### INDEX: {idx_name} ###'
go
SELECT
    {key_expr} AS key_value,
    COUNT(*) AS key_count
FROM [{table_name}].[{index_name}]
GROUP BY {group_by_expr}
HAVING COUNT(*) > 1
ORDER BY key_count DESC
go
"""
            chunks.append(sql)
        except Exception:
            continue
    return "\n".join(chunks)


def _parse_dup_output(raw: str) -> dict[str, list[tuple[str, int]]]:
    results: dict[str, list[tuple[str, int]]] = {}
    current_index = None

    for line in raw.splitlines():
        line = line.strip()
        marker = re.match(r"### INDEX: (.+?) ###", line)
        if marker:
            current_index = marker.group(1)
            continue
        if not current_index or not line:
            continue

        low = line.lower()
        if low.startswith("dup_key") or low.startswith("---") or low.startswith("(") or "error" in low or "msg " in low:
            continue

        parts = line.rsplit(None, 1)
        if len(parts) != 2:
            continue
        key_value, count_str = parts
        try:
            count = int(count_str)
            if count > 1:
                results.setdefault(current_index, []).append((key_value, count))
        except ValueError:
            continue

    return results


def _isql_failed(raw: str) -> str | None:
    msg_error = re.search(r"Msg \d+, Level \d+, State", raw)
    if msg_error:
        snippet_match = re.search(r"Msg \d+,.*?\n.*?\n(.*?)(?:\n|$)", raw)
        snippet = snippet_match.group(1).strip() if snippet_match else raw[:200]
        return f"Sybase error — {snippet}"

    failure_markers = [
        "localization-related structures", "Login failed", "Unable to connect",
        "CT-LIBRARY error", "DB-LIBRARY error", "command not found",
    ]
    for marker in failure_markers:
        if marker.lower() in raw.lower():
            return marker
    return None


def _progress_file_path(sid: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"dup_check_{sid.lower()}_progress.json")


def _write_progress(sid: str, phase: str, batch_num: int, total_batches: int, start_time: float) -> None:
    try:
        elapsed_seconds = time.time() - start_time
        percent = (batch_num / total_batches) * 100 if total_batches else 0
        avg_time_per_batch = elapsed_seconds / batch_num if batch_num > 0 else 0
        eta_minutes = ((total_batches - batch_num) * avg_time_per_batch) / 60

        progress = {
            "status": "running", "phase": phase, "batch": f"{batch_num}/{total_batches}",
            "progress": round(percent, 1), "time_elapsed": round(elapsed_seconds / 60, 1),
            "eta_minutes": round(eta_minutes, 1), "last_update": datetime.now().isoformat(),
        }
        with open(_progress_file_path(sid), "w") as f:
            json.dump(progress, f)
    except Exception as error:
        print(f"[PROGRESS] ❌ ERROR: {error}")


def get_scan_progress(sid: str) -> str:
    progress_file = _progress_file_path(sid)
    if not os.path.exists(progress_file):
        return f"❌ No scan in progress for {sid}"

    try:
        with open(progress_file) as f:
            progress = json.load(f)

        if progress.get("status") == "complete":
            return f"✅ Scan for {sid} is COMPLETE. Check the full results in chat."

        return f"""
╔════════════════════════════════════════════════════════════╗
║        Duplicate Key Scan Progress for {sid}
╠════════════════════════════════════════════════════════════╣
║ Status:        {progress.get('status', 'unknown')}
║ Phase:         {progress.get('phase', 'unknown')}
║ Progress:      {progress.get('batch', 'unknown')} ({progress.get('progress', 0):.1f}%)
║ Time Elapsed:  {progress.get('time_elapsed', 0):.1f} minutes
║ ETA:           {progress.get('eta_minutes', 0):.1f} minutes
║ Last Update:   {progress.get('last_update', 'unknown')}
╚════════════════════════════════════════════════════════════╝
"""
    except Exception as error:
        return f"❌ Error reading progress: {error}"


def _phase_2_batched_sequential(tables, ase_host, ssh_user, ssh_key, ssh_password, isql_base, sid):
    batches = [tables[i:i + DUP_CHECK_BATCH_SIZE] for i in range(0, len(tables), DUP_CHECK_BATCH_SIZE)]
    print(f"[DUP-CHECK] Phase 2 — SEQUENTIAL: Processing {len(batches)} batch(es) of {DUP_CHECK_BATCH_SIZE} tables")

    all_indexes: dict[str, list[str]] = {}
    errors: list[str] = []
    start_time = time.time()

    for batch_num, batch_tables in enumerate(batches, 1):
        if batch_num % 100 == 0:
            _write_progress(sid, "Phase 2", batch_num, len(batches), start_time)

        helpidx_sql = _build_sp_helpindex_batch(batch_tables)
        helpidx_path = f"/tmp/sp_helpindex_{sid.lower()}_batch{batch_num}.sql"

        batch_success = False
        for attempt in range(1, DUP_CHECK_MAX_RETRIES + 1):
            try:
                sftp_write_file(ase_host, ssh_user, ssh_key, ssh_password, helpidx_path, helpidx_sql)
                cmd = f"{isql_base} -i {helpidx_path}"
                success, raw_helpidx, _err = _run_isql_ssh(ase_host, ssh_user, ssh_key, ssh_password, cmd)

                if not success:
                    if attempt < DUP_CHECK_MAX_RETRIES:
                        time.sleep(5)
                        continue
                    raise Exception("SSH failed after max retries")

                fail = _isql_failed(raw_helpidx)
                if fail:
                    if attempt < DUP_CHECK_MAX_RETRIES:
                        time.sleep(5)
                        continue
                    raise Exception(f"isql error: {fail}")

                all_indexes.update(_parse_sp_helpindex_batch(raw_helpidx))
                batch_success = True
                break
            except Exception as error:
                if attempt < DUP_CHECK_MAX_RETRIES:
                    time.sleep(5)
                else:
                    errors.append(f"Batch {batch_num}: {error}")
                continue

        print(f"[DUP-CHECK] Batch {batch_num}/{len(batches)}: {'✅' if batch_success else 'SKIPPED'}")

    print(f"[DUP-CHECK] Phase 2 (Sequential) complete — {len(all_indexes)} indexes found")
    return all_indexes, errors


def _phase_2_batched_parallel(tables, ase_host, ssh_user, ssh_key, ssh_password, isql_base, sid):
    batches = [tables[i:i + DUP_CHECK_BATCH_SIZE] for i in range(0, len(tables), DUP_CHECK_BATCH_SIZE)]
    print(f"[DUP-CHECK] Phase 2 — PARALLEL: {len(batches)} batch(es), {DUP_CHECK_PARALLEL_WORKERS} workers")

    all_indexes: dict[str, list[str]] = {}
    errors: list[str] = []
    lock = Lock()
    batch_queue: Queue = Queue()
    for batch_num, batch_tables in enumerate(batches, 1):
        batch_queue.put((batch_num, batch_tables))
    total_batches = len(batches)
    start_time = time.time()

    def worker(worker_id):
        while not batch_queue.empty():
            try:
                batch_num, batch_tables = batch_queue.get(timeout=1)
            except Exception:
                break

            helpidx_sql = _build_sp_helpindex_batch(batch_tables)
            helpidx_path = f"/tmp/sp_helpindex_{sid.lower()}_batch{batch_num}.sql"

            for attempt in range(1, DUP_CHECK_MAX_RETRIES + 1):
                try:
                    sftp_write_file(ase_host, ssh_user, ssh_key, ssh_password, helpidx_path, helpidx_sql)
                    cmd = f"{isql_base} -i {helpidx_path}"
                    success, raw_helpidx, _err = _run_isql_ssh(ase_host, ssh_user, ssh_key, ssh_password, cmd, timeout=DUP_CHECK_ISQL_TIMEOUT)

                    if not success:
                        if attempt < DUP_CHECK_MAX_RETRIES:
                            time.sleep(5)
                            continue
                        raise Exception("SSH failed")

                    fail = _isql_failed(raw_helpidx)
                    if fail:
                        if attempt < DUP_CHECK_MAX_RETRIES:
                            time.sleep(5)
                            continue
                        raise Exception(f"isql error: {fail}")

                    batch_indexes = _parse_sp_helpindex_batch(raw_helpidx)
                    with lock:
                        all_indexes.update(batch_indexes)
                        print(f"[DUP-CHECK] Worker {worker_id}: Batch {batch_num} ✅ {len(batch_indexes)} indexes")
                        _write_progress(sid, "phase_2", batch_num, total_batches, start_time)
                    break
                except Exception as error:
                    if attempt < DUP_CHECK_MAX_RETRIES:
                        time.sleep(5)
                    else:
                        with lock:
                            errors.append(f"Batch {batch_num}: {error}")
                    continue

            batch_queue.task_done()

    workers = [Thread(target=worker, args=(worker_id,), daemon=True) for worker_id in range(1, DUP_CHECK_PARALLEL_WORKERS + 1)]
    for t in workers:
        t.start()
    batch_queue.join()

    print(f"[DUP-CHECK] Phase 2 (Parallel) complete — {len(all_indexes)} indexes found")
    return all_indexes, errors


def _phase_2_main(tables, ase_host, ssh_user, ssh_key, ssh_password, isql_base, sid):
    if DUP_CHECK_USE_PARALLEL:
        return _phase_2_batched_parallel(tables, ase_host, ssh_user, ssh_key, ssh_password, isql_base, sid)
    return _phase_2_batched_sequential(tables, ase_host, ssh_user, ssh_key, ssh_password, isql_base, sid)


def check_case_sensitivity_duplicates(request: SidRequest, *, config: AppConfig) -> str:
    sid = request.sid
    server = find_sap_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found in config."

    ase_host = server.ase_host or server.pashost
    ase_servername, ase_dbname, ase_user, ase_password = server.ase_servername, server.ase_dbname, server.ase_user, server.ase_password
    ssh_user = server.ase_os_user or server.sapadm
    ssh_key, ssh_password = server.key, server.password or ""

    missing = [k for k, v in {"ase_servername": ase_servername, "ase_dbname": ase_dbname, "ase_user": ase_user, "ase_password": ase_password}.items() if not v]
    if missing:
        return f"❌ Missing ASE config field(s) for {sid}: {', '.join(missing)}. Add them to the sap_server entry in config.json."

    isql_base = f"env LANG=C isql -S {ase_servername} -U {ase_user} -P {ase_password} -D {ase_dbname}"

    try:
        tbl_path = f"/tmp/find_tables_{sid.lower()}.sql"
        sftp_write_file(ase_host, ssh_user, ssh_key, ssh_password, tbl_path, _FIND_TABLES_WITH_UNIQUE_IDX_SQL)

        cmd1 = f"{isql_base} -i {tbl_path}"
        _success, raw_tables, _err = _run_isql_ssh(ase_host, ssh_user, ssh_key, ssh_password, cmd1)

        fail = _isql_failed(raw_tables)
        if fail:
            return f"❌ isql failed during table discovery for {sid} ({fail}).\n\nRaw isql output:\n{raw_tables}"

        tables = _parse_table_list(raw_tables)
        if not tables:
            return f"⚠️ No tables with unique indexes found for {sid} — nothing to check, or isql output was unparseable.\n\nRaw isql output:\n{raw_tables}"

        all_indexes, _phase2_errors = _phase_2_main(tables, ase_host, ssh_user, ssh_key, ssh_password, isql_base, sid)
        if not all_indexes:
            return "⚠️ Phase 2 failed: No indexes found"

        indexes = all_indexes
        index_list = list(indexes.items())
        index_batches = [index_list[i:i + 20] for i in range(0, len(index_list), 20)]

        findings: dict[str, list[tuple[str, int]]] = {}
        scan_start_time = time.time()

        for batch_num, index_batch in enumerate(index_batches, 1):
            batch_dict = dict(index_batch)
            dup_sql = _build_index_dup_check_sql(batch_dict)
            dup_path = f"/tmp/check_dups_{sid.lower()}_batch{batch_num}.sql"

            if batch_num % 100 == 0 or batch_num == 1:
                _write_progress(sid, "Phase 3", batch_num, len(index_batches), scan_start_time)

            for attempt in range(1, DUP_CHECK_MAX_RETRIES + 1):
                try:
                    sftp_write_file(ase_host, ssh_user, ssh_key, ssh_password, dup_path, dup_sql)
                    cmd3 = f"{isql_base} -i {dup_path}"
                    success, raw_dups, _err = _run_isql_ssh(ase_host, ssh_user, ssh_key, ssh_password, cmd3, timeout=DUP_CHECK_ISQL_TIMEOUT)

                    if not success:
                        if attempt < DUP_CHECK_MAX_RETRIES:
                            time.sleep(5)
                            continue
                        raise Exception("SSH failed after max retries")

                    fail = _isql_failed(raw_dups)
                    if fail:
                        if attempt < DUP_CHECK_MAX_RETRIES:
                            time.sleep(5)
                            continue
                        raise Exception(f"isql error: {fail}")

                    findings.update(_parse_dup_output(raw_dups))
                    break
                except Exception:
                    if attempt < DUP_CHECK_MAX_RETRIES:
                        time.sleep(5)
                    continue

        scope_note = f"Checked {len(indexes)} unique index(es) across {len(tables)} table(s) on {ase_servername}/{ase_dbname} via isql."

        if not findings:
            return f"✅ [{sid}] No duplicate key values found in any unique index (case-insensitive check).\n\n{scope_note}"

        lines = [f"\n{'=' * 70}", "FINAL REPORT: Duplicate Keys Found", f"{'=' * 70}\n",
                 f"❌ [{sid}] Duplicate key values found in {len(findings)} unique index(es) — these will block unique-index creation on IMPORT into HANA:\n"]
        for index_name, dups in findings.items():
            cols = indexes.get(index_name, [])
            lines.append(f"  {index_name}  [{', '.join(cols)}]  — {len(dups)} colliding key value(s)")
            for key, count in dups[:10]:
                lines.append(f"      '{key}' appears {count}x")
            if len(dups) > 10:
                lines.append(f"      ... and {len(dups) - 10} more")
        lines.append("\nExport will NOT fail on these — duplicates only break IMPORT when the target tries to rebuild the unique index. Resolve (merge/rename duplicates in ECC) before starting the conversion.")
        lines.append(f"\n{scope_note}")
        return "\n".join(lines)

    except Exception as error:
        return f"❌ Error running duplicate-key check for {sid}: {error}"
    finally:
        try:
            with open(_progress_file_path(sid), "w") as f:
                json.dump({"status": "complete"}, f)
        except Exception:
            pass
