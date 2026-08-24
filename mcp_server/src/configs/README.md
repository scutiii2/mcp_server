# src/configs/

Structured, per-deployment settings - host inventories, mail settings,
installed extensions, capability toggles. Loaded by
`infra/app_config.py` (see that module's docstring for the full loader
mechanics); paths come from `Settings.hosts_config_path` /
`email_config_path` / `extensions_config_path` /
`capabilities_config_path` in `config.py`.

- **`config_hosts.json`** - one entry per SSH-reachable host, keyed by
  the short name a tool call or `host://health/{name}` resource uses.
  Read by the `host_health` capability.
- **`config_email.json`** - SMTP settings and the standing
  recipient/approver lists. Read by the `otp` capability and by
  `infra/approvals.py` (approval-request emails). `smtp_server`/
  `smtp_port`/`security` depend on which provider `from` lives on -
  since JSON has no comments, the `.example` file only shows Gmail;
  the other two mainstream cases:

  ```jsonc
  // Outlook / Hotmail / Live / Microsoft 365
  {
    "smtp_server": "smtp.office365.com",
    "smtp_port": 587,
    "security": "starttls",
    "from": "you@outlook.com",
    "password": "${SMTP_PASSWORD}",
    "approver_emails": ["you@outlook.com"]
  }

  // Proton Mail - needs Proton Mail Bridge running locally first;
  // Proton doesn't expose SMTP directly even with an app password.
  // smtp_server/smtp_port come from the Bridge's own settings pane,
  // and the password is the Bridge-generated one, not the mailbox
  // password.
  {
    "smtp_server": "127.0.0.1",
    "smtp_port": 1025,
    "security": "starttls",
    "from": "you@proton.me",
    "password": "${SMTP_PASSWORD}",
    "approver_emails": ["you@proton.me"]
  }
  ```

  All three still need an app-specific password per this file's
  `email.py` docstring - Gmail and Outlook because of 2FA, Proton
  because Bridge issues its own.
- **`config_extensions.json`** - other MCP servers this server proxies
  tools from (see `infra/extensions.py`). Also written to at runtime by
  `POST`/`DELETE /extensions` (see `extension_routes.py`) - hand-edit it
  or add an extension live through that route, both end up here.
- **`config_capabilities.json`** - which built-in capabilities
  (`host_health`, `otp`) are enabled. A capability absent from this file
  is enabled; only an explicit `{"enabled": false}` turns one off:

  ```json
  { "host_health": { "enabled": true }, "otp": { "enabled": false } }
  ```

  Applied at startup by `run.py`, and also written to at runtime by
  `PATCH /capabilities/{name}` (see `capability_routes.py`) - toggling
  a capability through that route takes effect immediately, no restart
  needed, the same as `POST`/`DELETE /extensions` above for extensions.

Each file's top-level JSON *is* its content - there's no wrapper key.
Anything sensitive is a `${VAR}` placeholder resolved from
`../secrets/*.env` at load time, never a literal value in these files -
see `infra/app_config.py`'s docstring for the substitution syntax.
Every file has a committed `.example` twin with the same shape.

`config_hosts.json` and `config_email.json` are gitignored by exact path
even though this folder is otherwise committed - they carry this
deployment's real host list and approver addresses. `config_extensions.json`
and `config_capabilities.json` are ordinary committed files.
