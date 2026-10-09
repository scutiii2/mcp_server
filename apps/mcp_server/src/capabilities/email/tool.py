"""Email tools: deterministic delivery through the shared application service."""
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from src.capabilities.email import domain
from src.capabilities.email.contract import AuditResult, SendResult
from src.commands import command
from src.offload import offload
from src.server import mcp

Recipients = Annotated[str, Field(description="Recipient addresses separated by commas.")]
Subject = Annotated[str, Field(description="Email subject. Keep the same subject when replying in a thread.")]
Text = Annotated[str | None, Field(description="Plain-text body; required when HTML is omitted.", json_schema_extra={"input": "textarea"})]
Html = Annotated[str | None, Field(description="Optional HTML body; plain text is derived if body_text is omitted.", json_schema_extra={"input": "textarea"})]
Alias = Annotated[str, Field(description="Source name in the [EMBER | source] subject prefix.")]
Prefix = Annotated[bool, Field(description="Add the standard Ember source prefix to the subject.")]
Parent = Annotated[str, Field(description="Parent email's bracketed Message-ID returned by send or reply.")]
References = Annotated[str, Field(description="Optional earlier bracketed Message-IDs separated by spaces.")]


@command(name="send", description="Send an email")
@mcp.tool(meta={"keywords": ["email", "mail", "send", "notify"], "display_label": "Sending email"},
          annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@offload
def tool_email_sendEmail(to: Recipients, subject: Subject, body_text: Text = None,
                         body_html: Html = None, capability_alias: Alias = "email",
                         prefix_subject: Prefix = True) -> SendResult:
    """Send once using MCP's configured SMTP account; do not ask for SMTP credentials.
    Retain the returned Message-ID to use tool_email_replyEmail for updates in the same
    thread. SMTP acceptance does not guarantee inbox delivery. Never retry automatically
    after an ambiguous failure. Bodies are not kept in this capability's audit log.
    """
    return domain.send(to, subject, body_text, body_html, capability_alias, prefix_subject)


@command(name="reply", description="Send a reply in an email thread")
@mcp.tool(meta={"keywords": ["email", "mail", "reply", "thread"], "display_label": "Sending email reply"},
          annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@offload
def tool_email_replyEmail(to: Recipients, subject: Subject, in_reply_to: Parent,
                          body_text: Text = None, body_html: Html = None,
                          capability_alias: Alias = "email", prefix_subject: Prefix = True,
                          references: References = "") -> SendResult:
    """Send a threaded update using a previous Message-ID and optional ancestry.
    Use the same recipients, subject and prefix choice as the original email.
    Uses MCP SMTP configuration; never ask for credentials or automatically retry.
    """
    return domain.reply(to, subject, in_reply_to, body_text, body_html,
                        capability_alias, prefix_subject, references)


# MCP-only: account-scoped metadata for history surfaces, without message contents.
@mcp.tool(meta={"hidden": True, "keywords": ["email", "audit", "history", "delivery"], "display_label": "Reading email delivery history"},
          annotations=ToolAnnotations(readOnlyHint=True))
@offload
def tool_email_getAuditLog(limit: Annotated[int, Field(description="Newest delivery records to return.", ge=1, le=200)] = 50) -> AuditResult:
    """Return only the authenticated requester's delivery metadata; never bodies or codes."""
    return domain.audit(limit)
