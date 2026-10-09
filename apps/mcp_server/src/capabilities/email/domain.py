"""Typed email operations; shared services own transport, config and audit."""
from src.capabilities.email.contract import AuditResult, AuditRow, SendResult
from src.services import email_audit, email_delivery, identity_context
from src.services.watcher_recipients import parse_recipients


def send(to: str, subject: str, body_text: str | None = None, body_html: str | None = None,
         capability_alias: str = "email", prefix_subject: bool = True,
         *, in_reply_to: str | None = None, references: str = "") -> SendResult:
    if any(ord(char) < 32 or ord(char) == 127 for char in to + references):
        raise ValueError("Recipient and reference fields must not contain control characters.")
    try:
        recipients = parse_recipients(to)
    except ValueError:
        raise ValueError("Provide valid recipient email addresses.") from None
    message_id = email_delivery.deliver_email(recipients, subject, body_text, body_html=body_html,
        capability_alias=capability_alias, prefix_subject=prefix_subject,
        in_reply_to=in_reply_to, references=references.split())
    return SendResult(message_id=message_id, message="Email accepted by SMTP for delivery.")


def reply(to: str, subject: str, in_reply_to: str, body_text: str | None = None,
          body_html: str | None = None, capability_alias: str = "email",
          prefix_subject: bool = True, references: str = "") -> SendResult:
    if not in_reply_to:
        raise ValueError("A parent Message-ID is required for a reply.")
    return send(to, subject, body_text, body_html, capability_alias, prefix_subject,
                in_reply_to=in_reply_to, references=references)


def audit(limit: int = 50) -> AuditResult:
    rows = email_audit.read_audit(email_delivery.settings.email_audit_path,
                                 identity_context.current_username(), limit)
    return AuditResult(deliveries=[AuditRow(**row) for row in rows],
                       message=f"Showing {len(rows)} of your email delivery records.")
