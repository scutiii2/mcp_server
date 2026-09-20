# src/configs/

Structured, per-deployment settings - mail settings, installed
extensions and capability toggles. Loaded by
`services/app_config.py` (see that module's docstring for the full loader
mechanics); paths come from `Settings.email_config_path` /
`extensions_config_path` / `capabilities_config_path` in `config.py`.

- **`config_email.json`** - SMTP settings and the standing
  recipient list.
  `smtp_server`/
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
    "password": "${SMTP_PASSWORD}"
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
    "password": "${SMTP_PASSWORD}"
  }
  ```

  All three still need an app-specific password per this file's
  `email.py` docstring - Gmail and Outlook because of 2FA, Proton
  because Bridge issues its own.
- **`config_extensions.json`** - other MCP servers this server proxies
  tools from (see `services/extensions.py`). Also written to at runtime by
  `POST`/`DELETE /extensions` (see `extension_routes.py`) - hand-edit it
  or add an extension live through that route, both end up here.
- **`config_capabilities.json`** - which built-in capabilities
  (`server` - the toggle
  id, shorter than its folder name `server_manager` on purpose) are enabled. A capability absent
  from this file is enabled; only an explicit `{"enabled": false}` turns
  one off:

  ```json
  { "server": { "enabled": true } }
  ```

  Applied at startup by `run.py`, and also written to at runtime by
  `PATCH /capabilities/{name}` (see `capability_routes.py`) - toggling
  a capability through that route takes effect immediately, no restart
  needed, the same as `POST`/`DELETE /extensions` above for extensions.

Each file's top-level JSON *is* its content - there's no wrapper key.
Anything sensitive is a `${VAR}` placeholder resolved from
`../.secrets/*.env` at load time, never a literal value in these files -
see `services/app_config.py`'s docstring for the substitution syntax.
Every file has a committed `.example` twin with the same shape.

`config_email.json` is gitignored by exact path even though this
folder is otherwise committed - it carries this deployment's real
recipient addresses.
`config_extensions.json` and `config_capabilities.json` are ordinary
committed files.
