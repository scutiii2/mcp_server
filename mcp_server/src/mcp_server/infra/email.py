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


def send_email(config: EmailConfig, subject: str, body_html: str) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = ", ".join(config.to)
    message.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP(config.smtp_server, config.smtp_port, timeout=15) as server:
        server.starttls()
        server.login(config.from_address, config.password)
        server.sendmail(config.from_address, config.to, message.as_string())


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
