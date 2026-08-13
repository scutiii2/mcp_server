"""ABAP dump tools - list, analyze latest, analyze by crash key.

Each function here loads config, opens an RFC connection via
infra/rfc.py, calls the domain function(s), and formats the result.
``@mcp.tool()`` appears here and nowhere else.

``analyze_latest_dump_tool`` is a disclosed rewrite, not a faithful port
- the legacy ``analyze_latest_dump`` had three independent bugs that meant
it could never have executed successfully even once:
  1. Called bare ``Connection(**cfg)`` with no import of ``Connection``
     reachable anywhere in mcp_server.py or its imports - a guaranteed
     ``NameError``.
  2. Indexed ``latest["seqno"]`` on a dict that only ever has a
     ``"crash_key"`` key (see get_abap_dumps in domain.py) - a
     guaranteed ``KeyError``, even if bug 1 were fixed.
  3. Called ``analyze_dump_text(detail)`` where ``detail`` is already the
     dict *returned by* ``get_dump_detail()`` (with ``runtime_error``/
     ``program`` already computed) - passing a dict where
     ``analyze_dump_text`` expects a raw flist string would ``TypeError``,
     and the call was redundant besides.
Rewritten here to do what it was clearly trying to do: fetch the most
recent dump, get its detail (which already includes the analysis), and
format it - using ``get_dump_detail``'s result directly instead of
re-analyzing it.
"""

from __future__ import annotations

from mcp_server.capabilities.dumps.contract import AbapDumpsRequest
from mcp_server.capabilities.dumps.domain import (
    format_abap_dumps_report,
    format_dump_analysis_report,
    format_latest_dump_report,
    get_abap_dumps,
    get_dump_detail,
)
from mcp_server.config import settings
from mcp_server.infra.rfc import open_rfc_connection
from mcp_server.infra.sap_config import find_rfc_server, load_config
from mcp_server.server import mcp


@mcp.tool(description="List ABAP dumps from ST22 / SNAP table for a given SID and time range. Example: 'Show ABAP dumps in E4G last 24 hours'.")
def get_abap_dumps_tool(sid: str, hours: int = 24, dump_date: str = "") -> str:
    sid = sid.upper().strip()

    # Matches the legacy auto-conversion: a large hours value with no
    # explicit dump_date gets converted to a specific target date instead.
    if not dump_date and hours > 720:  # > 30 days
        from datetime import datetime, timedelta

        dump_date = (datetime.now() - timedelta(hours=hours)).strftime("%Y%m%d")

    request = AbapDumpsRequest(sid=sid, hours=hours, dump_date=dump_date)
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found in config."

    try:
        conn = open_rfc_connection(server)
        try:
            dumps = get_abap_dumps(conn, request)
        finally:
            conn.close()
        return format_abap_dumps_report(request, dumps)
    except Exception as error:
        return f"❌ Error while reading ABAP dumps for {sid}: {error}"


@mcp.tool(description="Analyze the single most recent ABAP dump for a SAP system.")
def analyze_latest_dump_tool(sid: str) -> str:
    sid = sid.upper().strip()
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found in config."

    try:
        conn = open_rfc_connection(server)
        try:
            dumps = get_abap_dumps(conn, AbapDumpsRequest(sid=sid, hours=24))
            if not dumps:
                return "No dumps found."
            latest = dumps[0]
            analysis = get_dump_detail(conn, latest.crash_key)
        finally:
            conn.close()
        return format_latest_dump_report(sid, latest, analysis)
    except Exception as error:
        return f"❌ Error analyzing latest dump: {error}"


@mcp.tool(description="Analyze an ABAP dump by its crash key (from get_abap_dumps_tool's output).")
def analyze_abap_dump_tool(sid: str, crash_key: str) -> str:
    sid = sid.upper().strip()
    config = load_config(settings.config_path)
    server = find_rfc_server(sid, config)
    if not server:
        return f"❌ SID '{sid}' not found"

    try:
        conn = open_rfc_connection(server)
        try:
            analysis = get_dump_detail(conn, crash_key)
        finally:
            conn.close()
        return format_dump_analysis_report(crash_key, analysis)
    except Exception as error:
        return f"❌ Error analyzing dump: {error}"
