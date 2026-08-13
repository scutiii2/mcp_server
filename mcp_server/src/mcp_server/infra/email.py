"""Email notifications via smtplib - genuinely new functionality, not a port.

The legacy ``trigger_kernel_update_from_windows()`` tried to
``from app import send_email, build_kernel_update_email`` at two points
during a kernel update. Neither function exists anywhere in the legacy
codebase (confirmed by searching the whole tree) - every call has always
raised ``ImportError``, been caught by a surrounding bare
``except Exception``, logged, and silently continued. This kernel update
tool has never actually sent an email, in any run, ever.

This module is a fresh design against the "email" section already
present in a real ``config.json`` (``smtp_server``, ``smtp_port``,
``from``, ``password``, ``to``) - there is no original implementation to
match, so the exact subject lines, HTML structure, and wording below are
new choices, not faithful ports. Uses only the stdlib
``smtplib``/``email.mime`` - no extra pip dependency needed, unlike every
other "new" piece of infra in this project (HANA, RFC, SAP AI Hub all
needed something heavy; this doesn't).

Callers are expected to treat a failed send the same way the legacy
code's intent clearly was: log it and keep going, never let an email
failure abort a kernel update. That's enforced at the call site in
capabilities/kernel/domain.py, not here - this module raises normally on
failure so tests can distinguish "sent" from "failed to send".
"""

from __future__ import annotations

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from mcp_server.infra.sap_config import EmailConfig


def send_email(config: EmailConfig, subject: str, body_html: str, *, to: list[str] | None = None) -> None:
    """``to`` defaults to ``config.to`` (kernel's existing behavior,
    unchanged) - pass it explicitly to target a different audience, e.g.
    user_provisioning sending to ``config.approver_emails`` or directly to
    a newly-created user's own address, neither of which should go to
    whoever's watching kernel-update notifications."""
    recipients = to if to is not None else config.to
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP(config.smtp_server, config.smtp_port, timeout=15) as server:
        server.starttls()
        server.login(config.from_address, config.password)
        server.sendmail(config.from_address, recipients, message.as_string())


def build_maintenance_started_email(sid: str, action: str, servers: list[str]) -> str:
    server_items = "".join(f"<li>{s}</li>" for s in servers if s)
    return f"""
    <html><body style="font-family: sans-serif;">
      <h2>🛠 SAP Maintenance Activity Started</h2>
      <p><b>SID:</b> {sid}</p>
      <p><b>Action:</b> {action}</p>
      <p><b>Servers involved:</b></p>
      <ul>{server_items}</ul>
    </body></html>
    """


def build_kernel_update_email(kernel_results: list[dict[str, str]]) -> str:
    rows = "".join(
        f"<tr><td>{r.get('sid', '')}</td><td>{r.get('host', '')}</td>"
        f"<td>{r.get('old_kernel', '')}</td><td>{r.get('new_kernel', '')}</td>"
        f"<td>{r.get('status', '')}</td></tr>"
        for r in kernel_results
    )
    return f"""
    <html><body style="font-family: sans-serif;">
      <h2>✅ SAP Kernel Update Completed</h2>
      <table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
        <tr style="background:#eee;"><th>SID</th><th>Host</th><th>Old Kernel</th><th>New Kernel</th><th>Status</th></tr>
        {rows}
      </table>
    </body></html>
    """


def build_user_creation_approval_email(
    *, sid: str, user_id: str, full_name: str, roles: list[str], requested_by: str, approve_url: str,
) -> str:
    role_items = "".join(f"<li>{r}</li>" for r in roles) or "<li><em>none requested</em></li>"
    return f"""
    <html><body style="font-family: sans-serif;">
      <h2>🔐 SAP User Creation — Approval Needed</h2>
      <p><b>System:</b> {sid}</p>
      <p><b>New user ID:</b> {user_id} ({full_name})</p>
      <p><b>Requested by:</b> {requested_by}</p>
      <p><b>Roles requested:</b></p>
      <ul>{role_items}</ul>
      <p>
        <a href="{approve_url}"
           style="display:inline-block;padding:10px 18px;background:#1a1a1a;color:#fff;text-decoration:none;border-radius:6px;">
          Review request
        </a>
      </p>
      <p style="color:#888;font-size:12px;">This link expires in 72 hours and can only be used once.</p>
    </body></html>
    """


def build_new_user_welcome_email(*, sid: str, user_id: str, full_name: str, initial_password: str) -> str:
    return f"""
    <html><body style="font-family: sans-serif;">
      <h2>👋 Your SAP account is ready</h2>
      <p>Hi {full_name},</p>
      <p>An SAP account has been created for you on <b>{sid}</b>.</p>
      <p><b>User ID:</b> {user_id}<br><b>Initial password:</b> {initial_password}</p>
      <p>You'll be required to change this password the first time you log on.</p>
    </body></html>
    """