"""ABAP short-dump analysis: RFC-based (SNAP table), not SSH or HANA SQL.

Faithful port of get_abap_dumps, get_dump_detail, analyze_dump_text,
parse_flist, and clean_program_name from sap_utils.py, plus the display
formatting from mcp_server.py's three dump tools.

Structured deliberately for testability despite the RFC dependency: the
actual parsing logic (_group_dumps_from_rfc_result,
_extract_dump_rows_from_rfc_result, analyze_dump_text, parse_flist) takes
plain dicts/strings and has zero pyrfc import anywhere - only
get_abap_dumps/get_dump_detail take an already-open RFC connection object
(dependency injection), so tests can pass a fake object with a `.call()`
method instead of needing pyrfc installed at all.

Disclosed bug fix: the legacy analyze_latest_dump (mcp_server.py) called
bare Connection(**cfg) with NO import of Connection reachable anywhere in
that file or its imports - a confirmed NameError on every call, not a
hypothetical. Fixed by routing through infra/rfc.py properly at the tool
layer; not reproduced here.

Disclosed as-is: analyze_dump_text's DBSQL_TABLE_UNKNOWN branch contains
incident-specific hardcoded values (RIS_V_SRC_IDX object name, source
line "202", a specific SELECT statement) that read like leftover
debugging artifacts from one real incident, not generalizable analysis
rules. Ported verbatim per the full-fidelity decision, not cleaned up -
worth revisiting if it produces misleading output for other objects.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from mcp_server.capabilities.dumps.contract import (
    AbapDumpsRequest,
    DumpAnalysis,
    DumpSummary,
)
from mcp_server.infra.rfc import RfcConnection


def parse_flist(flist: str) -> dict[str, str]:
    """Decode SNAP's length-prefixed FLIST field: repeating
    <2-char field id><3-digit length><value> groups."""
    pos = 0
    result: dict[str, str] = {}
    while pos + 5 <= len(flist):
        field_id = flist[pos:pos + 2]
        length_str = flist[pos + 2:pos + 5]
        if not length_str.isdigit():
            break
        length = int(length_str)
        value_start = pos + 5
        value_end = value_start + length
        result[field_id] = flist[value_start:value_end]
        pos = value_end
    return result


def clean_program_name(program: str) -> str:
    if not program:
        return ""
    program = program.strip()
    if "=====" in program:
        program = program.split("=====")[0].strip()
    return program


def analyze_dump_text(dump_text: str) -> DumpAnalysis:
    analysis = DumpAnalysis()

    parsed = parse_flist(dump_text)
    analysis.source_line = parsed.get("AL", "")

    analysis.runtime_error = parsed.get("FC", "").strip()
    analysis.program = clean_program_name(parsed.get("AP", ""))
    analysis.include = parsed.get("AI", "").strip()

    m = re.search(r"\bIF_[A-Z0-9_]+~[A-Z0-9_]+\b", dump_text.upper())
    if m:
        analysis.method = m.group(0)

    m = re.search(r"\bRIS_[A-Z0-9_]+\b", dump_text.upper())
    if m:
        analysis.missing_object = m.group(0)

    m = re.search(r"SQL\s*code\s*[:=]\s*(\d+)", dump_text, re.I)
    if m:
        analysis.sql_code = m.group(1)

    if not analysis.sql_code and analysis.runtime_error == "DBSQL_TABLE_UNKNOWN":
        analysis.sql_code = "208"

    m = re.search(r">>>>>\s*(\d+)", dump_text)
    if m:
        analysis.source_line = m.group(1)
    elif analysis.missing_object == "RIS_V_SRC_IDX":
        analysis.source_line = "202"

    if analysis.missing_object == "RIS_V_SRC_IDX":
        analysis.failing_statement = (
            "SELECT index_program_name\n  FROM ris_v_src_idx\n  INTO TABLE program_names"
        )

    if analysis.runtime_error == "DBSQL_TABLE_UNKNOWN":
        obj = analysis.missing_object or "the referenced database object"
        analysis.root_cause = (
            f"Database object {obj} does not exist in the database "
            f"or is not active/known in ABAP Dictionary."
        )
        analysis.recommendation = (
            "1. Check object in SE11.\n"
            "2. Verify whether table/view exists at DB level.\n"
            "3. Check recent transports for RIS/HANA search/index objects.\n"
            "4. Activate the DDIC object if inactive.\n"
            "5. If generated, regenerate related RIS/HANA index objects.\n"
            "6. Re-run the failed program/transaction."
        )
    elif analysis.runtime_error == "RAISE_EXCEPTION":
        analysis.root_cause = "An application exception was explicitly raised and not handled."
        analysis.recommendation = (
            "1. Open ST22 and check exception text.\n"
            "2. Review the include/method around termination point.\n"
            "3. Check SLG1 application logs if applicable.\n"
            "4. Check recent transports and input parameters."
        )
    elif analysis.runtime_error == "TSV_TNEW_PAGE_ALLOC_FAILED":
        analysis.root_cause = "Application server memory was exhausted while growing an internal table."
        analysis.recommendation = (
            "1. Check ST02 memory usage.\n"
            "2. Review internal table growth.\n"
            "3. Avoid broad SELECT statements.\n"
            "4. Use PACKAGE SIZE where possible.\n"
            "5. Review job/program selection criteria."
        )
    else:
        analysis.root_cause = "Runtime error detected. Review full ST22 dump text and source extract."
        analysis.recommendation = (
            "1. Open ST22 for full dump.\n"
            "2. Check termination program/include/line.\n"
            "3. Review recent transports and system changes.\n"
            "4. Check SM21 and application logs."
        )

    return analysis


def _group_dumps_from_rfc_result(rfc_result: dict[str, Any]) -> list[DumpSummary]:
    """Pure parsing: given RFC_READ_TABLE's raw {"DATA": [{"WA": "..."}]}
    shape, group SNAP rows by crash key (first row of each crash, SEQNO
    "000"). No RFC connection needed - takes the already-fetched result."""
    unique_dumps: dict[str, DumpSummary] = {}
    for row in rfc_result.get("DATA", []):
        fields = row["WA"].split("|")
        if len(fields) < 8:
            continue
        mandt, uname, datum, uzeit, seqno, host, modno, flist = (f.strip() for f in fields[:8])

        if seqno == "000":
            runtime_error = ""
            program = ""
            try:
                parsed = parse_flist(flist)
                runtime_error = parsed.get("FC", "")
                program = parsed.get("AP", "")
            except Exception as error:
                runtime_error = f"ERROR: {error}"

            crash_key = f"{mandt}|{uname}|{datum}|{uzeit}|{host}|{modno}"
            unique_dumps[crash_key] = DumpSummary(
                user=uname, date=datum, time=uzeit, host=host, mandt=mandt,
                crash_key=crash_key, runtime_error=runtime_error, program=program,
            )

    return list(unique_dumps.values())


def get_abap_dumps(conn: RfcConnection, request: AbapDumpsRequest) -> list[DumpSummary]:
    if request.dump_date:
        dump_date = request.dump_date.replace("-", "")
        options = [{"TEXT": f"DATUM EQ '{dump_date}'"}]
    else:
        since = (datetime.now() - timedelta(hours=request.hours)).strftime("%Y%m%d")
        options = [{"TEXT": f"DATUM GE '{since}'"}]

    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="SNAP",
        DELIMITER="|",
        FIELDS=[
            {"FIELDNAME": "MANDT"}, {"FIELDNAME": "UNAME"}, {"FIELDNAME": "DATUM"},
            {"FIELDNAME": "UZEIT"}, {"FIELDNAME": "SEQNO"}, {"FIELDNAME": "AHOST"},
            {"FIELDNAME": "MODNO"}, {"FIELDNAME": "FLIST"},
        ],
        OPTIONS=options,
        ROWCOUNT=200,
    )
    return _group_dumps_from_rfc_result(result)


def _extract_dump_rows_from_rfc_result(rfc_result: dict[str, Any]) -> list[dict[str, str]]:
    rows = []
    for row in rfc_result.get("DATA", []):
        fields = row.get("WA", "").split("|")
        if len(fields) < 8:
            continue
        row_mandt, row_uname, row_datum, row_uzeit, row_ahost, row_modno, row_seqno, row_flist = (
            f.strip() for f in fields[:8]
        )
        rows.append({
            "seqno": row_seqno, "flist": row_flist, "modno": row_modno, "ahost": row_ahost,
        })
    return rows


def get_dump_detail(conn: RfcConnection, crash_key_str: str) -> DumpAnalysis:
    """Full ABAP dump detail from SNAP using crash_key. Supported formats:
    mandt|uname|datum|uzeit|ahost  or  mandt|uname|datum|uzeit|ahost|modno"""
    parts = crash_key_str.split("|")
    if len(parts) < 5:
        return DumpAnalysis(
            runtime_error="Invalid crash key format",
            text=f"Expected: mandt|uname|datum|uzeit|ahost, got: {crash_key_str}",
        )

    mandt, uname, datum, uzeit, ahost = (p.strip() for p in parts[:5])
    modno = parts[5].strip() if len(parts) >= 6 else ""

    options = [
        {"TEXT": f"MANDT EQ '{mandt}'"},
        {"TEXT": f"AND UNAME EQ '{uname}'"},
        {"TEXT": f"AND DATUM EQ '{datum}'"},
        {"TEXT": f"AND UZEIT EQ '{uzeit}'"},
    ]
    if ahost:
        options.append({"TEXT": f"AND AHOST EQ '{ahost}'"})
    if modno:
        options.append({"TEXT": f"AND MODNO EQ '{modno}'"})

    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="SNAP",
        DELIMITER="|",
        FIELDS=[
            {"FIELDNAME": "MANDT"}, {"FIELDNAME": "UNAME"}, {"FIELDNAME": "DATUM"},
            {"FIELDNAME": "UZEIT"}, {"FIELDNAME": "AHOST"}, {"FIELDNAME": "MODNO"},
            {"FIELDNAME": "SEQNO"}, {"FIELDNAME": "FLIST"},
        ],
        OPTIONS=options,
        ROWCOUNT=5000,
    )

    rows = _extract_dump_rows_from_rfc_result(result)
    if not rows:
        return DumpAnalysis(
            runtime_error="No dump data found",
            text=f"No SNAP rows found for crash key: {crash_key_str}\n\nRFC OPTIONS USED:\n{options}",
        )

    rows.sort(key=lambda x: x["seqno"])
    full_flist = "".join(r["flist"] for r in rows)

    analysis = analyze_dump_text(full_flist)
    analysis.text = full_flist
    return analysis


# ── Tool-level report formatting ─────────────────────────────────────

def format_abap_dumps_report(request: AbapDumpsRequest, dumps: list[DumpSummary]) -> str:
    sid = request.sid.upper().strip()
    if not dumps:
        return f"✅ No ABAP dumps found in {sid} for last {request.hours} hours"

    lines = [f"🚨 ABAP Dumps in {sid}", f"Time Range : Last {request.hours} hours", "=" * 70]

    for idx, d in enumerate(dumps, start=1):
        lines.append(
            f"{idx}. 👤 User={d.user}\n"
            f"   📅 Date={d.date}\n"
            f"   🕒 Time={d.time}\n"
            # Faithful bug reproduction, not a typo here: the legacy code
            # does d.get('seqno', '') on a dict that only ever has a
            # 'crash_key' key, never 'seqno' - so this line always
            # rendered blank in the real tool. Preserved as-is since it
            # never crashes (unlike the two disclosed fixes elsewhere in
            # this file); worth fixing to show crash_key if you'd rather
            # have the field actually show something.
            "   🆔 SEQNO=\n"
            f"   🚨 Runtime Error={d.runtime_error or 'Unknown'}\n"
            f"   📄 Program={d.program or 'Unknown'}\n"
        )

    lines.append("=" * 70)
    lines.append(f"Total Dumps Found: {len(dumps)}")

    lines.append("")
    lines.append("🔍 Need further analysis?")
    lines.append("")
    lines.append("Select a dump number for detailed analysis:")
    lines.append("")
    for idx, d in enumerate(dumps, start=1):
        lines.append(f"  {idx}. {d.runtime_error or 'Unknown'} ({d.program or 'Unknown'})")
    lines.append("")
    lines.append("Examples:")
    lines.append("  • Analyze dump 1")
    lines.append("  • Analyze dump 2")
    lines.append("  • Analyze all dumps")

    return "\n".join(lines)


def format_latest_dump_report(sid: str, latest: DumpSummary, analysis: DumpAnalysis) -> str:
    return f"""
🚨 Latest ABAP Dump in {sid}

Runtime Error : {analysis.runtime_error}
Program       : {analysis.program}
User          : {latest.user}
Date          : {latest.date}
Time          : {latest.time}
SEQNO         : {latest.crash_key}
"""


def format_dump_analysis_report(crash_key: str, analysis: DumpAnalysis) -> str:
    lines = [
        f"\n{'=' * 70}",
        "🚨 ABAP DUMP ANALYSIS",
        f"{'=' * 70}\n",
        f"Crash Key        : {crash_key}",
        f"Runtime Error    : {analysis.runtime_error or 'Unknown'}",
        f"Program          : {analysis.program or 'Unknown'}",
        f"\n{'=' * 70}",
        "📋 DUMP TEXT (First 3000 chars)",
        f"{'=' * 70}\n",
        analysis.text[:3000] if analysis.text else "No text available",
        f"\n{'=' * 70}",
    ]
    return "\n".join(lines)
