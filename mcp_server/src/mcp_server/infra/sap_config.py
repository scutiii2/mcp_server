"""Typed configuration for SAP server connection details.

The legacy ``_load_config()`` returned a plain ``dict`` (or ``{}`` on any
error), so a typo'd key surfaced as a confusing failure three calls deep
inside a tool. A Pydantic model fails fast, at load time, with a message
that names the actual missing/invalid field.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class AdditionalAppServer(BaseModel):
    host: str
    instance: str


class SapServerConfig(BaseModel):
    sid: str
    host: str
    user: str = "root"
    key: str | None = None
    password: str | None = None
    # HANA SQL port connection, separate from the SSH details above -
    # optional, since not every capability needs direct DB access. None
    # of these fields means "no HANA access configured for this SID."
    hana_host: str | None = None
    hana_port: int = 30015
    hana_user: str | None = None
    hana_password: str | None = None
    # Multi-tier landscape fields, for orchestrating stop/start across the
    # DB/ASCS/PAS/additional-app-server topology via sapcontrol - genuinely
    # different from hana_host/hana_port/hana_user/hana_password above,
    # which are for direct HANA SQL-port queries (job_history resource),
    # not SSH-based sapcontrol commands against the DB instance. All tiers
    # share the single top-level `password` field for SSH auth - only the
    # OS username differs per tier (sapadm vs hanaadm) - matching the
    # legacy config's actual shape (confirmed against a real config.json).
    dbhost: str | None = None
    ascshost: str | None = None
    pashost: str | None = None
    sapadm: str | None = None
    hanaadm: str | None = None
    db_nr: str | None = None
    ascs_nr: str | None = None
    pas_nr: str | None = None
    additional_app_servers: list[AdditionalAppServer] = []
    # Windows-local path where kernel .SAR files are staged - used only by
    # the kernel-update tool, which (faithfully, per the legacy design)
    # assumes the MCP server process itself runs on Windows with local
    # filesystem access, not just network access to the SAP hosts. See
    # capabilities/kernel/domain.py's module docstring for why this
    # assumption was preserved rather than redesigned.
    kernel_dir: str | None = None
    # SAP ASE (Sybase) connection details - used only by the Conversion
    # category's case-sensitivity duplicate-key check, which queries the
    # ASE database via isql over SSH, not sapcontrol/HANA SQL. ase_host
    # and ase_os_user both fall back to pashost/sapadm respectively when
    # unset, matching the legacy config's own fallback behavior.
    ase_host: str | None = None
    ase_servername: str | None = None
    ase_dbname: str | None = None
    ase_user: str | None = None
    ase_password: str | None = None
    ase_os_user: str | None = None
    # Sybase/ASE connection details, used only by the conversion
    # duplicate-key-check tool (isql over SSH, not a real DB driver -
    # matches the legacy approach exactly). Genuinely distinct from the
    # HANA SQL-port fields above - this is an entirely different DB
    # engine, queried via a CLI tool over SSH rather than any client
    # library, confirmed against the real config.json's E4G entry.
    ase_host: str | None = None
    ase_servername: str | None = None
    ase_dbname: str | None = None
    ase_user: str | None = None
    ase_password: str | None = None
    ase_os_user: str | None = None


class RfcServerConfig(BaseModel):
    sid: str
    ashost: str
    sysnr: str = "00"
    client: str = "000"
    user: str
    passwd: str
    lang: str = "EN"


class EmailConfig(BaseModel):
    """SMTP settings for email notifications - a FOURTH config section
    ("email" in config.json), genuinely new functionality (see
    infra/email.py's module docstring - the legacy send_email/
    build_kernel_update_email it was meant to call never existed anywhere
    in the codebase). Field names match the "email" section already
    present in a real config.json, not invented here."""

    smtp_server: str
    smtp_port: int = 587
    from_address: str = Field(alias="from")
    password: str
    to: list[str] = []

    model_config = {"populate_by_name": True}


class AppConfig(BaseModel):
    sap_server: list[SapServerConfig] = []
    # A THIRD, separate config section - "sap" in config.json, not
    # "sap_server". Holds SAP RFC (Remote Function Call) connection
    # details, genuinely distinct from both the SSH fields above and the
    # HANA SQL-port fields: RFC talks to the SAP application server's own
    # gateway port using SAP's own protocol, authenticating as an SAP
    # user/client/password (not an OS user), used for ABAP-level data
    # access (dumps, jobs) that SSH/HANA-SQL can't reach directly.
    sap: list[RfcServerConfig] = []
    email: EmailConfig | None = None


def load_config(path: Path) -> AppConfig:
    with path.open(encoding="utf-8-sig") as config_file:
        raw = json.load(config_file)
    return AppConfig.model_validate(raw)


def find_sap_server(sid: str, config: AppConfig) -> SapServerConfig | None:
    sid_upper = sid.upper()
    return next((server for server in config.sap_server if server.sid.upper() == sid_upper), None)


def find_rfc_server(sid: str, config: AppConfig) -> RfcServerConfig | None:
    sid_upper = sid.upper()
    return next((server for server in config.sap if server.sid.upper() == sid_upper), None)
