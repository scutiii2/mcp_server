"""Approval landing page for user-provisioning requests.

Deliberately NOT an ``@mcp.tool()`` - see domain.py's module docstring
for why: if ``execute_approved_user_creation`` were a tool, anyone in a
chat session could call it directly with a guessed or leaked token and
skip approval entirely.

Two plain routes, mounted directly onto the same Starlette app
``mcp.streamable_http_app()`` already serves (see run.py) rather than
routed through chat_app - keeps every SAP-side concern inside
mcp_server, no new responsibility added to the Flask app.

GET only ever shows a confirmation page and never executes anything - a
GET with a side effect is a well-known trap for emailed action links:
corporate email security scanners routinely pre-fetch every link in an
inbound email to check for malware, which would silently "approve" a
user creation before a human ever opened the message. Only the POST (an
explicit button press on that page) actually creates the SAP account.

No authentication on this route - matches the already-disclosed gap on
/capabilities and /chat (see README's "Known gaps"). The "approved by"
field on the confirmation page is a self-reported name, not a verified
identity - fine to start with, worth revisiting before this runs
anywhere beyond localhost/VPN.

NOT runtime-verified: mounting extra routes onto
``mcp.streamable_http_app()``'s returned object via Starlette's
documented ``add_route()`` is written to Starlette's stable, public API,
but hasn't been confirmed against your installed mcp==1.28.0's actual
FastMCP internals in this sandbox (no network access to pip install it
here). See run.py for the mount point - first place to check if this
doesn't wire up as expected.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import HTMLResponse

from mcp_server.capabilities.user_provisioning.domain import execute_approved_user_creation
from mcp_server.config import settings
from mcp_server.infra import pending_requests
from mcp_server.infra.sap_config import load_config


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(f"""
    <html><body style="font-family: sans-serif; max-width: 560px; margin: 60px auto; padding: 0 20px;">
      {body}
    </body></html>
    """)


async def show_approval_page(request: Request) -> HTMLResponse:
    token = request.path_params["token"]
    pending = pending_requests.get(settings.pending_requests_path, token)

    if pending is None:
        return _page("<h2>❌ Unknown or invalid link</h2>")
    if pending.status != "pending":
        return _page(f"<h2>This request was already {pending.status}.</h2>")
    if pending.is_expired:
        return _page("<h2>⏱ This approval link has expired.</h2><p>Ask the requester to submit the request again.</p>")

    payload = pending.payload
    role_items = "".join(f"<li>{r}</li>" for r in payload.get("roles", [])) or "<li><em>none</em></li>"
    return _page(f"""
      <h2>🔐 Approve SAP user creation?</h2>
      <p><b>System:</b> {payload['sid']}</p>
      <p><b>User ID:</b> {payload['user_id']} ({payload['first_name']} {payload['last_name']})</p>
      <p><b>Requested by:</b> {payload['requested_by']}</p>
      <p><b>Roles:</b></p>
      <ul>{role_items}</ul>
      <form method="post">
        <label for="approved_by">Approved by (your name/email):</label><br>
        <input id="approved_by" type="text" name="approved_by" required
               style="width:100%;padding:8px;margin:8px 0;box-sizing:border-box;">
        <button type="submit"
                style="padding:10px 18px;background:#1a1a1a;color:#fff;border:none;border-radius:6px;cursor:pointer;">
          Approve &amp; create account
        </button>
      </form>
    """)


async def approve_and_execute(request: Request) -> HTMLResponse:
    token = request.path_params["token"]
    form = await request.form()
    approved_by = (form.get("approved_by") or "").strip() or "unknown"

    config = load_config(settings.config_path)
    result = execute_approved_user_creation(
        token, config=config, pending_db_path=settings.pending_requests_path, approved_by=approved_by,
    )
    icon = "✅" if result.success else "❌"
    return _page(f"<h2>{icon} {result.message}</h2>")