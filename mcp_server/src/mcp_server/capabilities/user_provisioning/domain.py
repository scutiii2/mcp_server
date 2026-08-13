"""SAP user creation: approval-gated, two separate entry points.

Genuinely new (no legacy source to port from - unlike most of this
project's other categories), and structured differently from most of
them on purpose:

``request_sap_user_creation`` is the ONLY function called from an
``@mcp.tool()`` (see tool.py). It validates the request against the
target system (user doesn't already exist, requested roles actually
exist - RFC_READ_TABLE against USR02/AGR_DEFINE, same pattern jobs/ and
dumps/ already use for read-only lookups) and, if that passes, stores a
pending request (infra/pending_requests.py) and emails an approval link.
It never creates a real SAP account.

``execute_approved_user_creation`` does the actual BAPI_USER_CREATE1 +
role assignment. It is deliberately NOT decorated with ``@mcp.tool()``
and is never imported by tool.py - only approval_routes.py calls it,
triggered by a human clicking "approve" on the emailed link, not by
anything the chat LLM can invoke directly. If this were also a tool,
anyone in a chat session could call it directly with a guessed or
leaked token and skip approval entirely, defeating the entire point of
the two-phase design. See approval_routes.py's module docstring for the
matching GET-vs-POST reasoning on the web side of this same boundary.

Matches capabilities/control's and capabilities/kernel's convention
(domain.py takes ``config: AppConfig`` directly and owns its own RFC
connection lifecycle) rather than capabilities/jobs's/dumps's (domain.py
takes an already-open ``conn``, tool.py manages its lifecycle) - this
capability's orchestration (RFC validation, then pending-request
persistence, then email) doesn't fit cleanly into "tool.py opens one
connection, calls one domain function, closes it," so it follows the
"domain.py owns everything, tool.py stays a few lines" convention
instead, same reasoning as kernel/domain.py.

Field names in the BAPI_USER_CREATE1 call below (``ADDRESS``,
``LOGONDATA``, ``PASSWORD.BAPIPWD``) are SAP's standard, widely
documented structure names for this BAPI - not runtime-verified against
your specific ECC/S4HANA release or RFC SDK typing in this sandbox (no
network access to a real system here). First place to check if the
create call fails with a field-not-found-style RFC error.
"""

from __future__ import annotations

import secrets
import string
from pathlib import Path

from mcp_server.capabilities.user_provisioning.contract import (
    ExecuteApprovedUserCreationResult,
    RequestSapUserCreation,
    RequestSapUserCreationResult,
)
from mcp_server.infra import pending_requests
from mcp_server.infra.email import build_new_user_welcome_email, build_user_creation_approval_email, send_email
from mcp_server.infra.rfc import RfcConnection, open_rfc_connection
from mcp_server.infra.sap_config import AppConfig, find_rfc_server


_TOKEN_TTL_HOURS = 72


def _check_user_exists(conn: RfcConnection, user_id: str) -> bool:
    result = conn.call(
        "RFC_READ_TABLE",
        QUERY_TABLE="USR02",
        DELIMITER="|",
        OPTIONS=[{"TEXT": f"BNAME = '{user_id.upper()}'"}],
        FIELDS=[{"FIELDNAME": "BNAME"}],
        ROWCOUNT=1,
    )
    return bool(result.get("DATA"))


def _validate_roles(conn: RfcConnection, roles: list[str]) -> tuple[list[str], list[str]]:
    """Split requested roles into ones that actually exist in AGR_DEFINE
    and ones that don't - catching a typo'd role name before the account
    exists is better than after. One RFC round trip per role rather than
    a single batched OR-condition query - simpler to read and correct,
    and role lists on a single request are typically small; worth
    batching later if that stops being true."""
    if not roles:
        return [], []

    valid: list[str] = []
    invalid: list[str] = []
    for role in roles:
        result = conn.call(
            "RFC_READ_TABLE",
            QUERY_TABLE="AGR_DEFINE",
            DELIMITER="|",
            OPTIONS=[{"TEXT": f"AGR_NAME = '{role.upper()}'"}],
            FIELDS=[{"FIELDNAME": "AGR_NAME"}],
            ROWCOUNT=1,
        )
        (valid if result.get("DATA") else invalid).append(role.upper())
    return valid, invalid


def _generate_initial_password() -> str:
    """Random password meeting typical SAP complexity rules (upper +
    digit + symbol + mixed alphanumerics). SAP forces a password change
    at first logon for a fresh BAPI_USER_CREATE1-created account by
    default, so no extra flag is set for that here - confirm against
    your system's actual password policy if that assumption is wrong.

    Never logged, never put in any tool response or pending-request
    payload - generated fresh at execution time and only ever handed to
    send_email() below, directly to the new user."""
    alphabet = string.ascii_letters + string.digits
    return (
        secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.digits)
        + secrets.choice("!@#$%")
        + "".join(secrets.choice(alphabet) for _ in range(9))
    )


def request_sap_user_creation(
    request: RequestSapUserCreation,
    *,
    config: AppConfig,
    pending_db_path: Path,
    public_base_url: str,
) -> RequestSapUserCreationResult:
    server = find_rfc_server(request.sid, config)
    if server is None:
        return RequestSapUserCreationResult(
            sid=request.sid,
            user_id=request.user_id,
            approval_requested=False,
            message=f"❌ RFC config not found for SID '{request.sid}'. Add it to config.json's 'sap' section.",
        )

    if not config.email or not config.email.approver_emails:
        return RequestSapUserCreationResult(
            sid=request.sid,
            user_id=request.user_id,
            approval_requested=False,
            message="❌ No approver configured - add 'email.approver_emails' to config.json before requesting user creation.",
        )

    conn = open_rfc_connection(server)
    try:
        if _check_user_exists(conn, request.user_id):
            return RequestSapUserCreationResult(
                sid=request.sid,
                user_id=request.user_id,
                approval_requested=False,
                message=f"❌ User '{request.user_id.upper()}' already exists on {request.sid}.",
            )
        valid_roles, invalid_roles = _validate_roles(conn, request.roles)
    finally:
        conn.close()

    if request.roles and not valid_roles:
        return RequestSapUserCreationResult(
            sid=request.sid,
            user_id=request.user_id,
            roles_invalid=invalid_roles,
            approval_requested=False,
            message=f"❌ None of the requested roles exist on {request.sid}: {', '.join(invalid_roles)}",
        )

    user_id = request.user_id.upper()
    payload = {
        "sid": request.sid,
        "user_id": user_id,
        "first_name": request.first_name,
        "last_name": request.last_name,
        "email": request.email,
        "user_type": request.user_type,
        "roles": valid_roles,
        "requested_by": request.requested_by,
    }
    token = pending_requests.create(pending_db_path, "user_provisioning", payload, ttl_hours=_TOKEN_TTL_HOURS)
    approve_url = f"{public_base_url}/approvals/user-provisioning/{token}"

    try:
        send_email(
            config.email,
            subject=f"🔐 Approval needed: new SAP user {user_id} on {request.sid}",
            body_html=build_user_creation_approval_email(
                sid=request.sid,
                user_id=user_id,
                full_name=f"{request.first_name} {request.last_name}",
                roles=valid_roles,
                requested_by=request.requested_by,
                approve_url=approve_url,
            ),
            to=config.email.approver_emails,
        )
    except Exception as error:
        return RequestSapUserCreationResult(
            sid=request.sid,
            user_id=user_id,
            token=token,
            roles_validated=valid_roles,
            roles_invalid=invalid_roles,
            approval_requested=False,
            message=(
                f"⚠️ Validated OK, but the approval email failed to send: {error}. "
                f"The request is still pending (token: {token}) - share the approval link manually if needed."
            ),
        )

    note = f" Note: role(s) not found and skipped: {', '.join(invalid_roles)}." if invalid_roles else ""
    return RequestSapUserCreationResult(
        sid=request.sid,
        user_id=user_id,
        token=token,
        roles_validated=valid_roles,
        roles_invalid=invalid_roles,
        approval_requested=True,
        message=f"✅ Approval request sent for {user_id} on {request.sid}.{note}",
    )


def execute_approved_user_creation(
    token: str,
    *,
    config: AppConfig,
    pending_db_path: Path,
    approved_by: str,
) -> ExecuteApprovedUserCreationResult:
    pending = pending_requests.get(pending_db_path, token)
    if pending is None:
        return ExecuteApprovedUserCreationResult(
            sid="", user_id="", success=False, user_created=False, message="❌ Unknown or invalid approval token."
        )
    if pending.capability != "user_provisioning":
        return ExecuteApprovedUserCreationResult(
            sid="", user_id="", success=False, user_created=False, message="❌ Token is not for a user-provisioning request."
        )
    if pending.status != "pending":
        return ExecuteApprovedUserCreationResult(
            sid=pending.payload.get("sid", ""),
            user_id=pending.payload.get("user_id", ""),
            success=False,
            user_created=False,
            message=f"❌ This request was already {pending.status} - approval links are one-time use.",
        )
    if pending.is_expired:
        return ExecuteApprovedUserCreationResult(
            sid=pending.payload.get("sid", ""),
            user_id=pending.payload.get("user_id", ""),
            success=False,
            user_created=False,
            message="❌ This approval link has expired (72h). Ask the requester to submit it again.",
        )

    payload = pending.payload
    sid, user_id = payload["sid"], payload["user_id"]

    server = find_rfc_server(sid, config)
    if server is None:
        return ExecuteApprovedUserCreationResult(
            sid=sid, user_id=user_id, success=False, user_created=False,
            message=f"❌ RFC config no longer found for SID '{sid}'.",
        )

    conn = open_rfc_connection(server)
    try:
        # Defensive re-check: config/landscape may have changed in the
        # (potentially long) gap between the original request and this
        # approval, so don't trust the first check alone.
        if _check_user_exists(conn, user_id):
            return ExecuteApprovedUserCreationResult(
                sid=sid, user_id=user_id, success=False, user_created=False,
                message=f"❌ User '{user_id}' already exists on {sid} - not creating.",
            )

        initial_password = _generate_initial_password()
        create_result = conn.call(
            "BAPI_USER_CREATE1",
            USERNAME=user_id,
            ADDRESS={"FIRSTNAME": payload["first_name"], "LASTNAME": payload["last_name"], "E_MAIL": payload["email"]},
            PASSWORD={"BAPIPWD": initial_password},
            LOGONDATA={"USTYP": payload["user_type"]},
        )
        create_errors = [r["MESSAGE"] for r in create_result.get("RETURN", []) if r.get("TYPE") == "E"]
        if create_errors:
            return ExecuteApprovedUserCreationResult(
                sid=sid, user_id=user_id, success=False, user_created=False, message="❌ " + "; ".join(create_errors)
            )

        roles_assigned: list[str] = []
        roles_failed: list[str] = []
        for role in payload.get("roles", []):
            assign_result = conn.call("BAPI_USER_ACTGROUPS_ASSIGN", USERNAME=user_id, ACTIVITYGROUPS=[{"AGR_NAME": role}])
            if any(r.get("TYPE") == "E" for r in assign_result.get("RETURN", [])):
                roles_failed.append(role)
            else:
                roles_assigned.append(role)

        # The single most common real-world bug with BAPI_USER_CREATE1:
        # forgetting this call. Every BAPI above reports success on its
        # own RETURN table, but nothing actually persists without an
        # explicit commit - skip this and the account silently vanishes
        # after the RFC connection closes.
        conn.call("BAPI_TRANSACTION_COMMIT", WAIT="X")
    finally:
        conn.close()

    pending_requests.mark_executed(pending_db_path, token, approved_by=approved_by)

    base_message = f"✅ User '{user_id}' created on {sid}."
    if roles_failed:
        base_message += f" Role(s) failed to assign: {', '.join(roles_failed)}."

    if config.email:
        try:
            send_email(
                config.email,
                subject=f"👋 Your SAP account on {sid} is ready",
                body_html=build_new_user_welcome_email(
                    sid=sid,
                    user_id=user_id,
                    full_name=f"{payload['first_name']} {payload['last_name']}",
                    initial_password=initial_password,
                ),
                to=[payload["email"]],
            )
        except Exception as error:
            return ExecuteApprovedUserCreationResult(
                sid=sid, user_id=user_id, success=True, user_created=True,
                roles_assigned=roles_assigned, roles_failed=roles_failed,
                message=f"{base_message} Welcome email failed to send ({error}) - deliver the initial password manually.",
            )

    return ExecuteApprovedUserCreationResult(
        sid=sid, user_id=user_id, success=True, user_created=True,
        roles_assigned=roles_assigned, roles_failed=roles_failed, message=base_message,
    )