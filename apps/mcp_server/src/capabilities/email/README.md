# capabilities/email/

Shared outgoing email for MCP notifications and Ember account emails. Uses the
standard [capability conventions](../README.md).

## Tools

| Tool | Purpose | Connection |
|---|---|---|
| `tool_email_sendEmail` | Send one email and return its Message-ID | SMTP |
| `tool_email_replyEmail` | Send a threaded reply and return its Message-ID | SMTP |
| `tool_email_getAuditLog` | MCP-only, owner-scoped delivery metadata | Local SQLite |

## Slash commands

| Tool | Slash command | Parameters |
|---|---|---|
| `tool_email_sendEmail` | `/email send` | <ul><li>`to` — required. Comma-separated addresses.</li><li>`subject` — required.</li><li>`body_text` — optional; required without HTML.</li><li>`body_html` — optional; plain text is derived when no text is given.</li><li>`capability_alias` — optional, default `email`. Subject source.</li><li>`prefix_subject` — optional, default `true`.</li></ul> |
| `tool_email_replyEmail` | `/email reply` | <ul><li>`to` — required.</li><li>`subject` — required; preserve the original subject.</li><li>`in_reply_to` — required. Parent Message-ID.</li><li>`body_text`, `body_html` — optional; supply at least one.</li><li>`capability_alias` — optional, default `email`.</li><li>`prefix_subject` — optional, default `true`; match the original.</li><li>`references` — optional, default empty. Space-separated ancestor IDs.</li></ul> |

## Typical workflow

| Sequence | Tool | Explanation |
|---|---|---|
| 1 | *(manual - no tool)* | Configure MCP SMTP and enable Email. |
| 2 | `tool_email_sendEmail` | Send the initial message; retain its Message-ID. |
| 3 | `tool_email_replyEmail` | Send an update with its parent and optional references. Retain the new ID. |
| 4 | `tool_email_getAuditLog` | Inspect your delivery metadata. |

## Configuration and integration

Reads MCP's existing `configs/config_email.json` via `settings.email_config_path`.
Use `configs/config_email.json.example` as the format reference, configuring SMTP
host, port, From, password and security on MCP only. No config is created by a send.
Existing deployments must refresh capabilities and switch **Email** online; new
example configurations enable it. Switching it offline blocks both local MCP
notifications and Ember sends. SMTP config changes take effect per send.

MCP producers call `services.email_delivery.deliver_email`; it enforces the live
switch, loads config, and uses the common `services.email` transport. Ember calls
the MCP send tool with its template body and `prefix_subject=false`. Every email
gets the automatic-message notice. No new `run.py` import is needed: discovery
loads this folder dynamically.

Replies use `In-Reply-To` and a deduplicated `References` chain, always with a new
Message-ID. The caller stores IDs; no mailbox or message bodies are stored here.
Actual conversation grouping depends on the receiving email client. SMTP
acceptance is reported accurately and does not promise inbox delivery. Partial
recipient refusal is an error; do not automatically retry an ambiguous send.

The existing internal-token middleware protects remote calls when configured.
Hidden metadata tools still enforce owner filtering. Sending remains subject to
Ember's existing tool-execution permissions and approval rules. The capability
supports explicitly addressed mail; review who receives tool-execution access.

Audit stores timestamp, caller, outcome, recipient count and generated Message-ID
in `specifics/email/.data/audit.db` (override `MCP_EMAIL_AUDIT_PATH`). It stores no
addresses, subjects, bodies, codes or raw errors. The history tool returns only
the authenticated caller's records; no identity returns no records. Internal
capability-owned job watchers attribute delivery to the watcher owner; Ember system emails
use service identity `ember`.
