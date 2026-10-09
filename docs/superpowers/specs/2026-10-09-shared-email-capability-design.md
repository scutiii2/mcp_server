# Shared MCP email capability

Status: approved by the user; implemented on codex/shared-email-capability.

## Intended outcome

The user wants an emailing capability in `mcp_server`, used by both MCP's own notifications and Ember's emails. SMTP delivery and credentials have one owner: `mcp_server`. Ember sends its invite and verification messages by calling the capability through its existing authenticated MCP transport.

Assumption carried forward from the preceding discussion: the capability also supports outgoing email threads. Incoming mailbox access is outside this change.

## Current behavior

- `apps/mcp_server/src/services/email.py` builds multipart notifications, prefixes subjects, appends the automatic-message notice, and creates a Message-ID without returning it. It has no reply headers.
- `apps/mcp_server/src/capabilities/watchers/utils/notify.py` calls this SMTP service directly and records sent, skipped, or failed outcomes.
- `apps/Ember/ember_api/src/services/email_service.py` independently delivers invite and verification messages through SMTP.
- Ember wires its injectable `EmailSender` in `src/app.py`. Its `services/mcp_session.py` provides authenticated MCP sessions.
- MCP capabilities are discovered dynamically and can be enabled or disabled.

## Approaches

1. Recommended: one email capability with a shared delivery service. Local MCP callers use its application entry point in process; Ember calls its MCP tool. Both paths enforce the capability's enabled state and share validation, delivery, and audit behavior.
2. Make MCP call its own HTTP endpoint for every notification. This centralizes invocation but adds loopback networking and session failure modes to background notifications.
3. Wrap the current sender as a tool while leaving existing senders unchanged. This adds a capability but fails the requested single delivery path.

## Capability and shared delivery

Add `apps/mcp_server/src/capabilities/email/`, with alias `email`, using the established contract/domain/tool, help, documentation, and audit conventions. Expose a send tool and a reply tool; reply requires a parent Message-ID. Return a human-readable outcome and the generated Message-ID after SMTP accepts the message.

Keep reusable SMTP transport and delivery orchestration under `src/services/`, as required by the capability conventions. The capability domain and local notification producers use the same application entry point. SMTP remains a lower-level implementation detail, not a separate send path for callers. Local calls must honor the live email capability switch without importing reloadable tool modules or making self-HTTP requests.

Accept explicit recipients, subject, plain text and optional HTML. Preserve existing MCP notification subject prefixes and notices. Preserve Ember's existing subject wording and plain-text templates through an explicit presentation option rather than adding an unwanted capability prefix. Validate header values and recipient lists before opening SMTP connections. Do not return SMTP credentials or raw message contents in errors.

SMTP credentials remain in MCP's existing email configuration. No new dependencies are expected. Ship the capability enabled in the example configuration; existing installations must enable it through their normal capability controls. Document that setup requirement.

## Outgoing threads

Each outgoing message retains its own Message-ID. A reply adds `In-Reply-To` for its parent and a validated `References` chain supplied by the caller. Return its Message-ID so callers can retain it for subsequent replies. Keep the subject consistent for related messages. No automatic threading of invite or verification emails is required.

This first version does not store message bodies or invent a persistent mailbox. Callers own the IDs they need to retain. Thread rendering ultimately depends on the recipient's email client.

## MCP's own notifications

Route watcher notifications through the shared capability entry point. Preserve owner-only recipients, HTML rendering, and the existing sent/skipped/failed strings. Missing email configuration must not create a real config file as a side effect. Disabled email delivery records a skipped outcome and does not interrupt the watcher.

## Ember integration

Replace production `SmtpEmailSender` wiring with an MCP-backed `EmailSender`. Reuse `mcp_session`, the configured MCP URL, and the internal token. Keep `send_invite` and `send_email_verification` signatures and fake injection intact. Ember continues to own templates, code generation, expiry, and account behavior; MCP owns delivery.

Treat transport failure, disabled/missing capability, tool errors, and malformed results as `EmailDeliveryError`, preserving current registration and resend responses. Do not automatically retry ambiguous sends, since SMTP acceptance followed by transport failure could otherwise duplicate mail.

Update documentation and configuration diagnostics so Ember no longer asks for local SMTP credentials. Do not read, copy, or modify deployed secrets. Explain how an operator configures the existing MCP email configuration and enables the capability.

## Access and audit

Use existing internal-token protection. A hidden tool is not an authorization boundary: email tools remain subject to Ember's server-side execution policy and normal approval rules. Keep verification and invite bodies and codes out of persisted tool-argument/traffic logs; review existing logging paths during implementation before sending them through MCP. Audit delivery metadata without bodies, codes, credentials, or raw SMTP exception text. Audit access must follow existing capability conventions.

## Verification

- Mock SMTP and inspect actual MIME output: new messages, reply headers, references, unique IDs, text/HTML, and preserved subjects/notices.
- Verify invalid addresses and injected header newlines fail before opening a connection.
- Verify capability discovery, tool registration, help, audit metadata, and enabled/disabled behavior.
- Verify watcher delivery and skipped/failed reporting use the shared entry point.
- Test the MCP-backed Ember sender with success, upstream failure, tool error, disabled capability, and malformed responses.
- Run existing registration, invite, verification, resend, and email-change tests with injected fakes.
- Exercise an in-process MCP integration test with mocked SMTP, including internal-token handling, and inspect logging behavior for sensitive payloads.
- Run appropriate MCP and Ember API suites. No real emails are sent during verification.

## Review boundaries

Implementation will touch the new capability, shared MCP email services, watcher notification adapter, Ember email adapter and app wiring, relevant diagnostics/documentation, and tests. No frontend changes, database migration, mailbox provider integration, credential migration, or deployment is planned.
