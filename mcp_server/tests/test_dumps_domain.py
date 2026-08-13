"""Domain tests for ABAP dumps - fake RFC connection objects (matching the
RfcConnection Protocol's .call() interface), no pyrfc import anywhere in
this file or in domain.py's testable functions.

FLIST test fixtures are built programmatically via _build_flist() rather
than hand-counted length-prefixed strings - manually counting field
lengths is exactly the kind of arithmetic that produced a real bug
earlier in this session (a whitespace-count mismatch in a format-string
assertion), so this sidesteps that whole class of mistake by construction
instead of counting.
"""

from __future__ import annotations

from mcp_server.capabilities.dumps.contract import AbapDumpsRequest, DumpSummary
from mcp_server.capabilities.dumps.domain import (
    _extract_dump_rows_from_rfc_result,
    _group_dumps_from_rfc_result,
    analyze_dump_text,
    clean_program_name,
    format_abap_dumps_report,
    format_dump_analysis_report,
    format_latest_dump_report,
    get_abap_dumps,
    get_dump_detail,
    parse_flist,
)


def _build_flist(fields: dict[str, str]) -> str:
    """Programmatically encode fields into the length-prefixed FLIST
    format parse_flist() expects: <2-char id><3-digit length><value>."""
    return "".join(f"{field_id}{len(value):03d}{value}" for field_id, value in fields.items())


class FakeRfcConnection:
    """Matches domain.py's RfcConnection Protocol - just a .call() method
    returning a canned RFC_READ_TABLE-shaped result, and records what it
    was called with so tests can assert on the constructed OPTIONS."""

    def __init__(self, result: dict):
        self.result = result
        self.calls: list[dict] = []

    def call(self, function_name: str, **kwargs) -> dict:
        self.calls.append({"function_name": function_name, **kwargs})
        return self.result


# ── parse_flist / clean_program_name ─────────────────────────────────

def test_parse_flist_decodes_length_prefixed_fields():
    flist = _build_flist({"FC": "DBSQL_TABLE_UNKNOWN", "AP": "ZTEST_PROGRAM"})

    result = parse_flist(flist)

    assert result == {"FC": "DBSQL_TABLE_UNKNOWN", "AP": "ZTEST_PROGRAM"}


def test_parse_flist_empty_string():
    assert parse_flist("") == {}


def test_parse_flist_stops_at_malformed_length():
    # "FCabc..." - "abc" isn't digits, parsing should stop cleanly, not raise
    assert parse_flist("FCabcJUNK") == {}


def test_clean_program_name_strips_trailing_equals_padding():
    assert clean_program_name("ZTEST_PROGRAM=============") == "ZTEST_PROGRAM"


def test_clean_program_name_empty():
    assert clean_program_name("") == ""


# ── analyze_dump_text ─────────────────────────────────────────────────

def test_analyze_dump_text_dbsql_table_unknown():
    flist = _build_flist({"FC": "DBSQL_TABLE_UNKNOWN", "AP": "ZTEST_PROGRAM"})

    analysis = analyze_dump_text(flist)

    assert analysis.runtime_error == "DBSQL_TABLE_UNKNOWN"
    assert analysis.program == "ZTEST_PROGRAM"
    assert analysis.sql_code == "208"  # fallback for this specific error
    assert "does not exist in the database" in analysis.root_cause
    assert "SE11" in analysis.recommendation


def test_analyze_dump_text_raise_exception():
    flist = _build_flist({"FC": "RAISE_EXCEPTION", "AP": "ZOTHER_PROGRAM"})

    analysis = analyze_dump_text(flist)

    assert analysis.runtime_error == "RAISE_EXCEPTION"
    assert "explicitly raised" in analysis.root_cause


def test_analyze_dump_text_unknown_error_gets_generic_recommendation():
    flist = _build_flist({"FC": "SOME_OTHER_ERROR"})

    analysis = analyze_dump_text(flist)

    assert analysis.runtime_error == "SOME_OTHER_ERROR"
    assert "Review full ST22 dump text" in analysis.root_cause


def test_analyze_dump_text_extracts_sql_code_when_present():
    flist = _build_flist({"FC": "SOME_ERROR"}) + " SQL code: 942 extra text"

    analysis = analyze_dump_text(flist)

    assert analysis.sql_code == "942"


# ── _group_dumps_from_rfc_result ─────────────────────────────────────

def test_group_dumps_only_takes_seqno_000_rows():
    flist = _build_flist({"FC": "RAISE_EXCEPTION", "AP": "ZPROG"})
    rfc_result = {
        "DATA": [
            {"WA": f"800|jdoe|20260810|120000|000|host1|0|{flist}"},
            {"WA": "800|jdoe|20260810|120000|001|host1|0|ignored-not-seqno-000"},
        ]
    }

    dumps = _group_dumps_from_rfc_result(rfc_result)

    assert len(dumps) == 1
    assert dumps[0].user == "jdoe"
    assert dumps[0].runtime_error == "RAISE_EXCEPTION"
    assert dumps[0].program == "ZPROG"
    assert dumps[0].crash_key == "800|jdoe|20260810|120000|host1|0"


def test_group_dumps_skips_short_rows():
    rfc_result = {"DATA": [{"WA": "too|few|fields"}]}
    assert _group_dumps_from_rfc_result(rfc_result) == []


def test_group_dumps_empty_result():
    assert _group_dumps_from_rfc_result({"DATA": []}) == []


# ── get_abap_dumps (via FakeRfcConnection) ───────────────────────────

def test_get_abap_dumps_uses_hours_based_options_when_no_date_given():
    conn = FakeRfcConnection({"DATA": []})

    get_abap_dumps(conn, AbapDumpsRequest(sid="E4G", hours=48))

    options = conn.calls[0]["OPTIONS"]
    assert "DATUM GE" in options[0]["TEXT"]


def test_get_abap_dumps_uses_exact_date_when_dump_date_given():
    conn = FakeRfcConnection({"DATA": []})

    get_abap_dumps(conn, AbapDumpsRequest(sid="E4G", dump_date="2026-08-10"))

    options = conn.calls[0]["OPTIONS"]
    assert "DATUM EQ '20260810'" in options[0]["TEXT"]  # dashes stripped


def test_get_abap_dumps_returns_grouped_summaries():
    flist = _build_flist({"FC": "RAISE_EXCEPTION", "AP": "ZPROG"})
    conn = FakeRfcConnection({"DATA": [{"WA": f"800|jdoe|20260810|120000|000|host1|0|{flist}"}]})

    dumps = get_abap_dumps(conn, AbapDumpsRequest(sid="E4G"))

    assert len(dumps) == 1
    assert dumps[0].runtime_error == "RAISE_EXCEPTION"


# ── get_dump_detail (via FakeRfcConnection) ──────────────────────────

def test_get_dump_detail_invalid_crash_key_format():
    conn = FakeRfcConnection({"DATA": []})

    analysis = get_dump_detail(conn, "too|few|parts")

    assert analysis.runtime_error == "Invalid crash key format"
    assert conn.calls == []  # never even attempted the RFC call


def test_get_dump_detail_no_rows_found():
    conn = FakeRfcConnection({"DATA": []})

    analysis = get_dump_detail(conn, "800|jdoe|20260810|120000|host1")

    assert analysis.runtime_error == "No dump data found"


def test_get_dump_detail_assembles_multi_row_flist_in_seqno_order():
    part1 = _build_flist({"FC": "RAISE"})
    part2 = _build_flist({"AP": "ZPROG"})
    conn = FakeRfcConnection({
        "DATA": [
            {"WA": f"800|jdoe|20260810|120000|host1|0|001|{part2}"},  # out of order on purpose
            {"WA": f"800|jdoe|20260810|120000|host1|0|000|{part1}"},
        ]
    })

    analysis = get_dump_detail(conn, "800|jdoe|20260810|120000|host1")

    # rows must be sorted by seqno before concatenation, so part1 (seqno
    # 000) comes before part2 (seqno 001) regardless of DATA order
    assert analysis.runtime_error == "RAISE"
    assert analysis.program == "ZPROG"


def test_get_dump_detail_includes_modno_filter_only_when_present():
    conn = FakeRfcConnection({"DATA": []})

    get_dump_detail(conn, "800|jdoe|20260810|120000|host1|5")

    options_text = " ".join(o["TEXT"] for o in conn.calls[0]["OPTIONS"])
    assert "MODNO EQ '5'" in options_text


# ── _extract_dump_rows_from_rfc_result ───────────────────────────────

def test_extract_dump_rows_skips_short_rows():
    assert _extract_dump_rows_from_rfc_result({"DATA": [{"WA": "short|row"}]}) == []


# ── report formatting ─────────────────────────────────────────────────

def test_format_abap_dumps_report_no_dumps():
    result = format_abap_dumps_report(AbapDumpsRequest(sid="e4g", hours=24), [])
    assert result == "✅ No ABAP dumps found in E4G for last 24 hours"


def test_format_abap_dumps_report_lists_dumps_and_selection_prompt():
    dumps = [
        DumpSummary(user="jdoe", date="20260810", time="120000", host="h1", mandt="800",
                    crash_key="800|jdoe|20260810|120000|h1|0", runtime_error="RAISE_EXCEPTION", program="ZPROG")
    ]
    result = format_abap_dumps_report(AbapDumpsRequest(sid="E4G", hours=24), dumps)

    assert "🚨 ABAP Dumps in E4G" in result
    assert "Total Dumps Found: 1" in result
    assert "Analyze dump 1" in result
    # disclosed faithful bug reproduction - SEQNO always blank in the real tool
    assert "🆔 SEQNO=\n" in result


def test_format_latest_dump_report():
    from mcp_server.capabilities.dumps.contract import DumpAnalysis

    latest = DumpSummary(user="jdoe", date="20260810", time="120000", host="h1", mandt="800",
                          crash_key="800|jdoe|20260810|120000|h1|0", runtime_error="RAISE_EXCEPTION", program="ZPROG")
    analysis = DumpAnalysis(runtime_error="RAISE_EXCEPTION", program="ZPROG")

    result = format_latest_dump_report("E4G", latest, analysis)

    assert "Latest ABAP Dump in E4G" in result
    assert "User          : jdoe" in result


def test_format_dump_analysis_report_truncates_to_3000_chars():
    from mcp_server.capabilities.dumps.contract import DumpAnalysis

    analysis = DumpAnalysis(runtime_error="X", program="Y", text="A" * 5000)

    result = format_dump_analysis_report("800|jdoe|...", analysis)

    assert "A" * 3000 in result
    assert "A" * 3001 not in result
