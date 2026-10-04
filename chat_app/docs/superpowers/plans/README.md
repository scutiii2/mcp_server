# docs/superpowers/plans/

One step-by-step implementation plan per feature (or per phase of the
AuthTemplate build), each with a checkbox (`- [ ]`) task list meant to be
executed by `superpowers:subagent-driven-development` or
`superpowers:executing-plans`, task-by-task. Each plan names its paired spec
under `../specs/` in its own header.

- `2026-08-21-authtemplate-foundation.md` - Phase 1: project skeleton,
  config/secrets loading, data layer, bootable app factory.
- `2026-08-21-authtemplate-security-pipeline.md` - Phase 2: rate limiting, IP
  filtering, headers, fingerprinting.
- `2026-08-21-authtemplate-auth-core.md` - Phase 3: the merged login/
  registration/logout flow, `@require_permission`, the bootstrap admin.
- `2026-08-21-authtemplate-admin-invites.md` - Phase 4: role/permission/
  account administration and invite generation (the Admin page).
- `2026-08-21-authtemplate-overview-account.md` - Phase 5: the Overview
  landing page, Account page, and shared sidebar chrome.
- `2026-08-22-logs-page.md` - the Logs page and its `LogEntry` subsystem.
- `2026-08-22-chat-capabilities-port.md` - porting the Chat and Capabilities
  pages (and the LLM chat subsystem behind them) from MCPArchitecture.
- `2026-08-23-chat-slash-commands-plan.md` - the Chat page's `/`
  slash-command system and its param autocomplete.

See [`../specs/README.md`](../specs/README.md) for the design spec each of
these implements.
