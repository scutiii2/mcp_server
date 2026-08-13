"""Domain tests for the approval-gated user-provisioning capability.

No real RFC connection, no real SMTP (``send_email`` patched at
``mcp_server.capabilities.user_provisioning.domain.send_email`` - the
point of use, not its definition site in infra/email.py - same
module-import-not-name-import reasoning test_chat_routes.py's docstring
already spells out for this codebase), and a real SQLite file via
pytest's ``tmp_path`` fixture for the pending-request store rather than
mocking it - it's cheap, fast, and exercising the real thing here is
more honest than mocking infra this test suite itself just added.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from mcp_server.capabilities.user_provisioning.contract import RequestSapUserCreation
from mcp_server.capabilities.user_provisioning.domain import (
    _check_user_exists,
    _validate_roles,
    execute_approved_user_creation,
    request_sap_user_creation,
)
from mcp_server.infra import pending_requests
from mcp_server.infra.sap_config import AppConfig, EmailConfig, RfcServerConfig


class FakeRfcConnection:
    """Unlike jobs'/dumps' FakeRfcConnection (a single canned result, or
    a fixed sequence keyed only by function name), this one resolves
    each call via a callback given the actual kwargs. Needed because this
    domain code calls "RFC_READ_TABLE" for two structurally different
    lookups (existence check against USR02, role validation against
    AGR_DEFINE) and "BAPI_USER_ACTGROUPS_ASSIGN" once per role, where the
    right answer depends on *which* role/table, not just call order."""

    def __init__(self, respond):
        self._respond = respond
        self.calls: list[dict] = []
        self.closed = False

    def call(self, function_name: str, **kwargs) -> dict:
        self.calls.append({"function_name": function_name, **kwargs})
        return self._respond(function_name, kwargs)

    def close(self) -> None:
        self.closed = True


def _rfc_server(sid: str = "E4G") -> RfcServerConfig:
    return RfcServerConfig(sid=sid, ashost="e4g-host", user="RFC_USER", passwd="x")


def _email_config(**overrides) -> EmailConfig:
    defaults = dict(
        smtp_server="smtp.example.com", from_address="sap@example.com", password="x",
        to=["ops@example.com"], approver_emails=["approver@example.com"],
    )
    defaults.update(overrides)
    return EmailConfig(**defaults)


def _config(*, with_rfc: bool = True, with_email: bool = True) -> AppConfig:
    return AppConfig(sap=[_rfc_server()] if with_rfc else [], email=_email_config() if with_email else None)


def _request(**overrides) -> RequestSapUserCreation:
    defaults = dict(
        sid="E4G", user_id="jdoe", first_name="Jane", last_name="Doe",
        email="jane.doe@example.com", roles=["Z_BASIC_USER"], requested_by="bob@example.com",
    )
    defaults.update(overrides)
    return RequestSapUserCreation(**defaults)


def _pending_payload(**overrides) -> dict:
    defaults = dict(
        sid="E4G", user_id="JDOE", first_name="Jane", last_name="Doe",
        email="jane.doe@example.com", user_type="A", roles=["Z_BASIC_USER"], requested_by="bob@example.com",
    )
    defaults.update(overrides)
    return defaults


def _user_does_not_exist_role_valid(function_name, kwargs):
    """Respond function for the "everything checks out" happy path: user
    doesn't exist, every requested role is valid."""
    return {"DATA": []} if kwargs.get("QUERY_TABLE") == "USR02" else {"DATA": [{"WA": "X"}]}


# ── _check_user_exists / _validate_roles ─────────────────────────────

def test_check_user_exists_true_when_rfc_returns_a_row():
    conn = FakeRfcConnection(lambda fn, kw: {"DATA": [{"WA": "JDOE"}]})
    assert _check_user_exists(conn, "jdoe") is True


def test_check_user_exists_false_when_rfc_returns_no_rows():
    conn = FakeRfcConnection(lambda fn, kw: {"DATA": []})
    assert _check_user_exists(conn, "jdoe") is False


def test_validate_roles_splits_valid_and_invalid():
    def respond(fn, kw):
        role = kw["OPTIONS"][0]["TEXT"]
        return {"DATA": [{"WA": "X"}]} if "Z_REAL_ROLE" in role else {"DATA": []}

    conn = FakeRfcConnection(respond)
    valid, invalid = _validate_roles(conn, ["Z_REAL_ROLE", "Z_TYPO_ROLE"])

    assert valid == ["Z_REAL_ROLE"]
    assert invalid == ["Z_TYPO_ROLE"]


def test_validate_roles_empty_input_short_circuits_with_no_rfc_calls():
    conn = FakeRfcConnection(lambda fn, kw: {"DATA": []})
    assert _validate_roles(conn, []) == ([], [])
    assert conn.calls == []


# ── request_sap_user_creation ────────────────────────────────────────

def test_request_fails_fast_when_sid_not_configured(tmp_path: Path):
    result = request_sap_user_creation(
        _request(sid="ZZZ"), config=_config(with_rfc=False),
        pending_db_path=tmp_path / "pending.db", public_base_url="http://localhost:8010",
    )
    assert result.approval_requested is False
    assert "ZZZ" in result.message


def test_request_fails_when_no_approver_configured(tmp_path: Path):
    result = request_sap_user_creation(
        _request(), config=_config(with_email=False),
        pending_db_path=tmp_path / "pending.db", public_base_url="http://localhost:8010",
    )
    assert result.approval_requested is False
    assert "approver" in result.message.lower()


def test_request_fails_when_user_already_exists(tmp_path: Path):
    fake = FakeRfcConnection(lambda fn, kw: {"DATA": [{"WA": "JDOE"}]})
    with patch("mcp_server.capabilities.user_provisioning.domain.open_rfc_connection", return_value=fake):
        result = request_sap_user_creation(
            _request(), config=_config(), pending_db_path=tmp_path / "pending.db",
            public_base_url="http://localhost:8010",
        )

    assert result.approval_requested is False
    assert "already exists" in result.message
    assert fake.closed is True  # always closed, even on the early-return path


def test_request_fails_when_no_requested_roles_are_valid(tmp_path: Path):
    fake = FakeRfcConnection(lambda fn, kw: {"DATA": []})  # user doesn't exist AND no role matches
    with patch("mcp_server.capabilities.user_provisioning.domain.open_rfc_connection", return_value=fake):
        result = request_sap_user_creation(
            _request(roles=["Z_TYPO"]), config=_config(), pending_db_path=tmp_path / "pending.db",
            public_base_url="http://localhost:8010",
        )

    assert result.approval_requested is False
    assert "Z_TYPO" in result.message


def test_request_happy_path_creates_pending_record_and_emails_approver(tmp_path: Path):
    fake = FakeRfcConnection(_user_does_not_exist_role_valid)
    db_path = tmp_path / "pending.db"

    with patch("mcp_server.capabilities.user_provisioning.domain.open_rfc_connection", return_value=fake), \
         patch("mcp_server.capabilities.user_provisioning.domain.send_email") as mock_send:
        result = request_sap_user_creation(
            _request(), config=_config(), pending_db_path=db_path, public_base_url="http://localhost:8010",
        )

    assert result.approval_requested is True
    assert result.token is not None
    assert result.roles_validated == ["Z_BASIC_USER"]

    # the pending record actually persisted, with what a later approval needs
    record = pending_requests.get(db_path, result.token)
    assert record.status == "pending"
    assert record.payload["user_id"] == "JDOE"
    assert record.payload["roles"] == ["Z_BASIC_USER"]

    # emailed the approver specifically, not the general "to" watchers list
    mock_send.assert_called_once()
    _, send_kwargs = mock_send.call_args
    assert send_kwargs["to"] == ["approver@example.com"]
    assert result.token in send_kwargs["body_html"]


def test_request_still_pending_if_approval_email_fails_to_send(tmp_path: Path):
    fake = FakeRfcConnection(_user_does_not_exist_role_valid)
    db_path = tmp_path / "pending.db"

    with patch("mcp_server.capabilities.user_provisioning.domain.open_rfc_connection", return_value=fake), \
         patch("mcp_server.capabilities.user_provisioning.domain.send_email", side_effect=RuntimeError("smtp down")):
        result = request_sap_user_creation(
            _request(), config=_config(), pending_db_path=db_path, public_base_url="http://localhost:8010",
        )

    assert result.approval_requested is False
    assert result.token is not None  # record still exists, just undelivered
    assert "smtp down" in result.message
    assert pending_requests.get(db_path, result.token).status == "pending"


# ── execute_approved_user_creation ───────────────────────────────────

def test_execute_rejects_unknown_token(tmp_path: Path):
    result = execute_approved_user_creation(
        "not-a-real-token", config=_config(), pending_db_path=tmp_path / "pending.db", approved_by="alice",
    )
    assert result.success is False
    assert "Unknown" in result.message


def test_execute_rejects_already_executed_token(tmp_path: Path):
    db_path = tmp_path / "pending.db"
    token = pending_requests.create(db_path, "user_provisioning", _pending_payload())
    pending_requests.mark_executed(db_path, token, approved_by="someone-else")

    result = execute_approved_user_creation(token, config=_config(), pending_db_path=db_path, approved_by="alice")

    assert result.success is False
    assert "already" in result.message.lower()


def test_execute_rejects_expired_token(tmp_path: Path):
    db_path = tmp_path / "pending.db"
    token = pending_requests.create(db_path, "user_provisioning", _pending_payload(), ttl_hours=-1)

    result = execute_approved_user_creation(token, config=_config(), pending_db_path=db_path, approved_by="alice")

    assert result.success is False
    assert "expired" in result.message.lower()


def test_execute_rejects_token_from_a_different_capability(tmp_path: Path):
    db_path = tmp_path / "pending.db"
    token = pending_requests.create(db_path, "some_other_capability", {"x": 1})

    result = execute_approved_user_creation(token, config=_config(), pending_db_path=db_path, approved_by="alice")

    assert result.success is False


def test_execute_happy_path_creates_user_assigns_roles_and_commits(tmp_path: Path):
    db_path = tmp_path / "pending.db"
    token = pending_requests.create(db_path, "user_provisioning", _pending_payload())

    def respond(fn, kw):
        if fn == "RFC_READ_TABLE":
            return {"DATA": []}  # defensive re-check: still doesn't exist
        if fn in ("BAPI_USER_CREATE1", "BAPI_USER_ACTGROUPS_ASSIGN", "BAPI_TRANSACTION_COMMIT"):
            return {"RETURN": []}
        return {}

    fake = FakeRfcConnection(respond)
    with patch("mcp_server.capabilities.user_provisioning.domain.open_rfc_connection", return_value=fake), \
         patch("mcp_server.capabilities.user_provisioning.domain.send_email") as mock_send:
        result = execute_approved_user_creation(token, config=_config(), pending_db_path=db_path, approved_by="alice")

    assert result.success is True
    assert result.user_created is True
    assert result.roles_assigned == ["Z_BASIC_USER"]
    assert result.roles_failed == []

    # the actual BAPI sequence happened, in order, including the commit -
    # this is the single most common real bug with BAPI_USER_CREATE1
    call_names = [c["function_name"] for c in fake.calls]
    assert "BAPI_USER_CREATE1" in call_names
    assert "BAPI_TRANSACTION_COMMIT" in call_names
    assert call_names.index("BAPI_TRANSACTION_COMMIT") > call_names.index("BAPI_USER_CREATE1")

    # token consumed - can't be replayed
    updated = pending_requests.get(db_path, token)
    assert updated.status == "executed"
    assert updated.approved_by == "alice"

    # welcome email went to the new user, not the approver
    mock_send.assert_called_once()
    _, send_kwargs = mock_send.call_args
    assert send_kwargs["to"] == ["jane.doe@example.com"]


def test_execute_defensive_recheck_blocks_creation_if_user_appeared_since_request(tmp_path: Path):
    """The gap between request and approval can be long - re-verify the
    user still doesn't exist rather than trusting the original check."""
    db_path = tmp_path / "pending.db"
    token = pending_requests.create(db_path, "user_provisioning", _pending_payload())

    fake = FakeRfcConnection(lambda fn, kw: {"DATA": [{"WA": "JDOE"}]})  # now exists
    with patch("mcp_server.capabilities.user_provisioning.domain.open_rfc_connection", return_value=fake):
        result = execute_approved_user_creation(token, config=_config(), pending_db_path=db_path, approved_by="alice")

    assert result.success is False
    assert "already exists" in result.message
    # not consumed - a genuinely blocked request can be retried once resolved
    assert pending_requests.get(db_path, token).status == "pending"


def test_execute_reports_bapi_error_without_creating_or_consuming_token(tmp_path: Path):
    db_path = tmp_path / "pending.db"
    token = pending_requests.create(db_path, "user_provisioning", _pending_payload())

    def respond(fn, kw):
        if fn == "RFC_READ_TABLE":
            return {"DATA": []}
        if fn == "BAPI_USER_CREATE1":
            return {"RETURN": [{"TYPE": "E", "MESSAGE": "User name already reserved"}]}
        return {"RETURN": []}

    fake = FakeRfcConnection(respond)
    with patch("mcp_server.capabilities.user_provisioning.domain.open_rfc_connection", return_value=fake):
        result = execute_approved_user_creation(token, config=_config(), pending_db_path=db_path, approved_by="alice")

    assert result.success is False
    assert result.user_created is False
    assert "already reserved" in result.message
    assert pending_requests.get(db_path, token).status == "pending"  # not consumed on failure


def test_execute_partial_role_assignment_failure_still_reports_success(tmp_path: Path):
    db_path = tmp_path / "pending.db"
    token = pending_requests.create(db_path, "user_provisioning", _pending_payload(roles=["Z_OK", "Z_FAILS"]))

    def respond(fn, kw):
        if fn == "RFC_READ_TABLE":
            return {"DATA": []}
        if fn == "BAPI_USER_ACTGROUPS_ASSIGN":
            role = kw["ACTIVITYGROUPS"][0]["AGR_NAME"]
            return {"RETURN": [{"TYPE": "E", "MESSAGE": "nope"}]} if role == "Z_FAILS" else {"RETURN": []}
        return {"RETURN": []}

    fake = FakeRfcConnection(respond)
    with patch("mcp_server.capabilities.user_provisioning.domain.open_rfc_connection", return_value=fake), \
         patch("mcp_server.capabilities.user_provisioning.domain.send_email"):
        result = execute_approved_user_creation(token, config=_config(), pending_db_path=db_path, approved_by="alice")

    assert result.success is True  # the account itself was created fine
    assert result.roles_assigned == ["Z_OK"]
    assert result.roles_failed == ["Z_FAILS"]
    assert "Z_FAILS" in result.message