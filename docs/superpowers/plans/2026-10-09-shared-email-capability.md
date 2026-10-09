# Shared Email Capability Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` for native execution, or `superpowers:subagent-driven-development` if the user chooses delegation. Steps use checkboxes for tracking. User approved this plan and native execution on a separate branch; implementation and verification are complete; the progress ledger records an existing intermittent question-event test failure.

**Goal:** Make MCP's email capability the delivery path for MCP notifications and Ember account emails, with optional outgoing reply headers.

**Architecture:** Preserve the reusable SMTP transport in MCP and introduce one capability-aware application service used by the email domain and local notification producers. Ember's injectable email sender becomes an authenticated MCP client, retaining its templates and account-flow interfaces.

**Tech Stack:** Python, existing FastMCP and Pydantic, stdlib SMTP/email/SQLite, Ember's existing MCP session and traffic recorder; no new packages.

**Spec:** [Approved design](../specs/2026-10-09-shared-email-capability-design.md).

## Global constraints

- SMTP credentials remain in MCP's existing email configuration; deployed secrets are neither read nor changed.
- Local and remote delivery obey the live `email` capability toggle.
- Existing watcher recipients, outcomes, subject prefixes, and automatic-message notices are preserved.
- Ember keeps existing invite/verification subjects, templates, injectable fakes, and API responses.
- Callers retain message IDs; no mailbox, body storage, automatic account-email threading, or database migration.
- No automatic retry of ambiguous sends and no real SMTP delivery during tests.
- Follow dynamic capability discovery rather than the scaffold skill's stale static-import instructions.
- Do not commit or push without user approval.

## Review focus

- Capability disabled or unregistered during a background notification: no SMTP connection and a recorded skipped outcome.
- SMTP accepts only some recipients: report incomplete delivery accurately without retrying accepted recipients.
- CR/LF in addresses, subjects, alias, parent ID, or references: reject before socket creation.
- Malformed or error MCP response: preserve `EmailDeliveryError`, never report success or expose codes.
- Reload and concurrent sends: shared dispatch stays usable and audit records remain consistent without message bodies.

## Task 1: Thread-aware SMTP transport

**Files:** Modify `apps/mcp_server/src/services/email.py`; extend `apps/mcp_server/tests/test_email.py`.

**Interfaces:** Extend existing `send_email(config, capability_alias, subject, body_html, *, to=None, body_text=None)` with `in_reply_to: str | None = None`, `references: list[str] | None = None`, and `prefix_subject: bool = True`; return the generated Message-ID as `str`. Keep existing defaults. Allow a plain-text-only message through `body_html: str | None` without synthesizing HTML.

- [x] Add tests asserting returned ID equals the MIME Message-ID, successive sends differ, reply has parent and references, duplicate references are removed in order, and parent is appended once.
- [x] Add tests for plain-only Ember content, exact unprefixed subject, existing multipart ordering/footer, and header injection failing before any SMTP constructor.
- [x] Cover invalid individual recipient entries and config From, empty recipients, invalid IDs, and nonempty SMTP refusal dictionaries. Reuse existing recipient validation only after rejecting newlines; do not let a splitter turn injected headers into additional recipients.
- [x] Run `python -m pytest tests/test_email.py -q` from `apps/mcp_server` and confirm new tests fail for the missing behavior.
- [x] Implement the signature extensions and validations, preserving SSL/STARTTLS/relay behavior. Treat any refused recipients as incomplete delivery and do not retry.
- [x] Re-run the transport tests and confirm all pass.

## Task 2: Capability-aware delivery and metadata audit

**Files:** Create `apps/mcp_server/src/services/email_delivery.py` and `email_audit.py`; add an email audit-path setting in `apps/mcp_server/src/config.py`; create `apps/mcp_server/tests/test_email_delivery.py`.

**Interfaces:** `deliver_email(to: list[str], subject: str, body_text: str | None, *, body_html: str | None = None, capability_alias: str = "email", prefix_subject: bool = True, in_reply_to: str | None = None, references: list[str] | None = None, config_path: Path | None = None, owner: str | None = None) -> str`. The internal-only `owner` defaults to request identity and is never a public tool argument. Define `EmailUnavailable` for missing/disabled capability or missing configuration and `EmailDeliveryError` for sanitized SMTP/config failures. Default audit path: `specifics/email/.data/audit.db`.

- [x] Check the live catalog or cache before new reusable services; if neither exists, search tagged source and record that fallback.
- [x] Add tests for enabled success, disabled and unregistered capability, missing config without example copying, invalid config, transport failure, and caller identity.
- [x] Add tests showing audit rows contain time, caller, outcome, recipient count and Message-ID, with no subject, addresses, bodies, codes, credentials, or raw exceptions. Query returns only the requesting owner's records; missing identity cannot read other callers' records.
- [x] Run `python -m pytest tests/test_email_delivery.py -q` and confirm the new module is missing.
- [x] Implement capability gating with existing `capability_registry.is_enabled`, explicit file existence check, `load_email_config`, and Task 1 transport. Use stdlib SQLite for bounded metadata queries and safe concurrent inserts. Record success/failure without turning an already accepted delivery into a retryable failure if audit persistence fails.
- [x] Re-run delivery and transport tests. Confirm sanitized errors and inspect captured logs for sentinel code/body strings.

## Task 3: Expose email send/reply tools

**Files:** Create `apps/mcp_server/src/capabilities/email/{__init__.py,contract.py,domain.py,tool.py,help.json,README.md,STATIC-GUIDELINES.md}`; modify `apps/mcp_server/configs/config_capabilities.json.example`; create `apps/mcp_server/tests/test_email_capability.py`; include email in `tests/test_tool_display_labels.py`.

**Interfaces:** Register `META` with folder/id `email`, label `Email`. Tools `tool_email_sendEmail`, `tool_email_replyEmail`, `tool_email_getAuditLog`. Send/reply take `to` as comma-separated addresses, `subject`, optional `body_text`/`body_html`, `capability_alias="email"`, and `prefix_subject=True`; reply additionally requires `in_reply_to` and accepts whitespace-separated `references=""`. Result: `message_id: str`, `message: str`; no bodies or codes in results. Audit result: metadata rows and `message`.

- [x] Add tests for tool schemas, `/email send` and `/email reply`, help consistency, display labels, and dynamic load/offline/online behavior.
- [x] Add an in-process FastMCP round trip with patched SMTP: verify structured result, reply headers, sanitized error, and captured logs excluding content. Check internal-token middleware acceptance/rejection using existing middleware test patterns.
- [x] Run `python -m pytest tests/test_email_capability.py -q` and confirm missing tools fail.
- [x] Implement thin offloaded tools, typed contracts, domain delegation to Task 2, discovery metadata, and documentation. Use send/reply annotations identifying external side effects. Audit is tool-only with `hidden` metadata and owner filtering enforced in the service.
- [x] Add only the example toggle; document enabling existing installations through capability controls. Avoid editing deployed config.
- [x] Run capability tests plus loader/help/display-label tests; verify discovery through test ASGI routes without launching the deployed server.

## Task 4: Route MCP notifications through the capability

**Files:** Modify `apps/mcp_server/src/capabilities/watchers/utils/notify.py` and its README email section; update `apps/mcp_server/tests/test_watch_notify.py` and relevant watcher tests.

**Interfaces:** Keep `send_watcher_email(...) -> str` and watcher outcome strings. Replace its transport/config dependencies with the Task 2 entry point, passing owner identity explicitly through the shared service's audit context when background threads lack request context.

- [x] Add tests proving owner-only recipients and original prefix/body pass through shared dispatch.
- [x] Add disabled/missing-config/transport-failure tests: `skipped: ...` or `failed: ...` is retained without aborting the watcher. Assert no raw exceptions or body contents leak into persisted detail.
- [x] Run `python -m pytest tests/test_watch_notify.py -q` and observe expected failures.
- [x] Replace direct SMTP use with shared delivery while preserving no-config side effects and best-effort behavior. Pass `owner=spec.owner` for audit attribution; never accept audit owner as a public tool argument.
- [x] Run watcher notification, user-watcher, and watcher-domain tests; search production MCP source to confirm no notification producer still calls SMTP directly.

## Task 5: Replace Ember SMTP with authenticated MCP delivery

**Files:** Modify `apps/Ember/ember_api/src/services/email_service.py`, `src/app.py`, `src/services/config_validation.py`, `README.md`, and email/config-validation tests. Remove only obsolete SMTP instructions from tracked setup documentation; do not read or edit `.env*` files.

**Interfaces:** Keep `EmailSender`, `EmailDeliveryError`, `render_template`, `send_invite`, and `send_email_verification`. Replace `SmtpEmailSender` with `McpEmailSender(url: str, internal_token: str | None, traffic: TrafficRecorder | None = None)`. Call `tool_email_sendEmail` with explicit recipient, original subject, template body, `capability_alias="ember"`, and `prefix_subject=False`; MCP appends the notice once.

- [x] Rewrite sender tests using an injected/mocked MCP session. Assert subjects, codes, expiry, destination, identity/internal-token headers, and exact tool arguments. No local SMTP constructor is used.
- [x] Test unreachable server, unknown/disabled tool, `isError`, malformed/non-dict structured content, missing/invalid Message-ID, and fallback JSON text responses. Each becomes a generic `EmailDeliveryError`; cancellation propagates; no automatic retry.
- [x] Test traffic counters and captured logs contain no code/body/recipient payload. System-generated account emails use a service identity rather than requiring a verified user session.
- [x] Run `python -m pytest tests/test_email_service.py -q` from `apps/Ember/ember_api` and confirm expected failures.
- [x] Implement the adapter with existing `mcp_session`, `identity_headers`, configured MCP URL/token, and traffic timing. Wire production sender in lifespan; preserve fake injection.
- [x] Update config diagnostics/tests to stop requiring Ember SMTP variables. Do not claim MCP email readiness from local config alone. Document MCP configuration, capability enablement, outage behavior, and removal of duplicate SMTP setup.
- [x] Run sender/config checks and registration/invite/verification/email-change tests with existing fakes.

## Task 6: Final verification and documentation review

- [x] Run complete MCP suite from `apps/mcp_server` and complete Ember API suite from `apps/Ember/ember_api` using available Python environments; record failures and distinguish pre-existing blockers with evidence.
- [x] Review every send path, live toggle behavior, SMTP partial failures, sanitized exception handling, dynamic reload, and concurrent audit insertion.
- [x] Review changed documentation/help against actual tool schemas and setup. Confirm no new packages, deployed credential edits, body persistence, frontend changes, or automatic retries.
- [x] Inspect `git diff --check` and final diff; report changed behavior, tests, setup needed, and any unresolved limitations. Leave changes uncommitted unless authorized.

## Execution handoff

Recommended: native execution in this existing worktree, since the tasks share the transport and delivery interfaces. The alternative is delegated implementation with independent task reviews. The user approved the plan and selected native execution on a separate branch. The completed code remains uncommitted on codex/shared-email-capability; see the progress ledger for verification evidence and baseline test limitations.
