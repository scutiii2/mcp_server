"""Invite and verification templates delivered through MCP's Email capability."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from string import Template
from typing import Protocol

import httpx

from src.services.mcp_session import identity_headers, mcp_session
from src.services.traffic import TrafficRecorder


TEMPLATE_DIR = Path(__file__).parent / "email_templates"

_TIMEOUT = httpx.Timeout(30.0, read=60.0)
_MESSAGE_ID = re.compile(r"<[^<>\s@\x00-\x1f\x7f]+@[^<>\s@\x00-\x1f\x7f]+>")


def render_template(name: str, **values: str) -> str:
    """Fill ``email_templates/<name>.txt``. ``KeyError`` on a missing value."""
    source = (TEMPLATE_DIR / f"{name}.txt").read_text(encoding="utf-8")
    return Template(source).substitute(values).strip()


class EmailDeliveryError(RuntimeError):
    """Sending failed (SMTP not configured, unreachable, auth rejected, ...)."""


class EmailSender(Protocol):
    async def send_invite(self, to: str, code: str, expires_at: datetime) -> None: ...

    async def send_email_verification(self, to: str, code: str, expires_at: datetime) -> None: ...


class McpEmailSender:
    """Use the shared MCP SMTP service; Ember owns templates, never credentials."""

    def __init__(self, url: str, internal_token: str | None, traffic: TrafficRecorder | None = None) -> None:
        self._url = url
        self._internal_token = internal_token
        self._traffic = traffic or TrafficRecorder()

    async def send_invite(self, to: str, code: str, expires_at: datetime) -> None:
        await self._send(
            to,
            "Your Ember invite code",
            render_template("invite", code=code, expires_at=f"{expires_at:%Y-%m-%d %H:%M}"),
        )

    async def send_email_verification(self, to: str, code: str, expires_at: datetime) -> None:
        await self._send(
            to,
            "Verify your Ember email",
            render_template("email_verification", code=code, expires_at=f"{expires_at:%Y-%m-%d %H:%M}"),
        )

    async def _send(self, to: str, subject: str, body: str) -> None:
        headers = identity_headers("ember", "", self._internal_token)
        # Account emails can precede login/verification; service identity is intentional.
        with self._traffic.timed("mcp_server", "email.send"):
            try:
                async with mcp_session(self._url, headers, _TIMEOUT) as session:
                    result = await session.call_tool("tool_email_sendEmail", {
                        "to": to, "subject": subject, "body_text": body,
                        "capability_alias": "ember", "prefix_subject": False,
                    })
                if getattr(result, "isError", None) is not False:
                    raise ValueError("Email tool failed")
                data = result.structuredContent
                if data is None:
                    data = json.loads("\n".join(getattr(block, "text", "") for block in result.content))
                message_id = data.get("message_id") if isinstance(data, dict) else None
                if not isinstance(message_id, str) or not _MESSAGE_ID.fullmatch(message_id):
                    raise ValueError("Invalid email tool result")
            except Exception:
                # Upstream exceptions and tool content may contain verification codes.
                # CancelledError propagates unchanged; no automatic retries.
                raise EmailDeliveryError(
                    "Email could not be sent. Check MCP Server connectivity, its Email capability and SMTP configuration; check delivery status before retrying."
                ) from None
