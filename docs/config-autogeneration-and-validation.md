# Config auto-generation and validation

Summary of the work done on `chat_app`, `ai_agent` and `mcp_server` so that a
missing or invalid config/secret no longer crashes startup with an opaque traceback.

Commits: `011b1e2`, `4c6ef5c`, `74f7506` (branch `home`).

## Problem

Starting `chat_app` on a fresh checkout failed with
`FileNotFoundError: Config file not found: chat_app/configs/config_app.json`,
because the real (gitignored) config files only exist as `.example` twins.

## 1. Auto-generate missing configs and secrets

If a real file is missing but `<name>.example` exists, it is copied to `<name>`.
With no example either, the previous behaviour is kept (raise for JSON configs,
empty dict for env files in `chat_app`).

| Project | Where | Behaviour |
|---|---|---|
| chat_app | `src/utils/config_loader.py` | `load_json_config` and `load_env_secrets` seed on demand; `load_all_json_configs` seeds every `*.json.example` in the directory |
| ai_agent | new `src/seed.py` (`seed_from_example`) | called before loading `secret_llm.env`, `config_servers.json`, `config_ai_agent_roles.json`, `config_llms.json`, `config_token_limits.json`. `config_agents.json` is untouched (its registry already tolerates a missing file and writes it at runtime) |
| mcp_server | `src/run.py`, `src/services/app_config.py` | `run.py` seeds every `.secrets/*.env.example` before loading env files; `load_config` seeds JSON configs |

Caveat: seeded secrets contain the example's placeholder values. Anything
required (`SECRET_KEY`, `INTERNAL_API_TOKEN`, API keys) must still be filled in.

## 2. chat_app: ConfigIssues page and redirect guard

- `src/services/config_validation.py` validates every chat_app `configs/*.json`
  and `secrets/*.env` without raising: unreadable file, invalid JSON, missing or
  mistyped keys, and placeholder values (`changeme`, `your_...`, `<...>`,
  `@example.com`, the dev fallback key). Blank `SECRET_KEY` and
  `INTERNAL_API_TOKEN` count as issues; SMTP is only checked when some SMTP value
  is set. Messages contain file and key names only, never secret values.
- `src/pages/ConfigIssues/` (`/configissues`) lists the issues as file / key /
  problem. The route is intentionally not login-gated, because a broken config can
  make login unusable. `config.issues.view` only controls the nav link.
- `install_config_guard()` adds a `before_request` hook: while any issue exists,
  every route redirects to `/configissues`. Exempt: that blueprint, `internal`,
  static files. Off when `TESTING` is set. Results are cached by file mtime, so
  fixing a file and reloading clears the redirect without a restart.
- `create_app` in `src/run.py` no longer crashes when `config_app.json` or the
  security configs are broken; it falls back to defaults so the page can render.
- Tests: `tests/test_config_validation.py` (5 tests).

Scope decision: chat_app only. Placeholder values count as issues.

Consequence: on a fresh clone, blank `SECRET_KEY` / `INTERNAL_API_TOKEN` in the
seeded secrets redirect every page to the issues page until filled in.

## 3. ai_agent: clean startup error

`src/server.py` wraps the import that resolves config at import time. A
configuration error (`AgentConfigError`, `AgentRoleError`, `ConfigError`, any
`FileNotFoundError` or `ValueError`) now prints

```
ai_agent cannot start - configuration error:
  <message>
```

and exits with status 1. Any other exception still propagates with its traceback.
Triggered by `AI_AGENT_PROVIDER is 'anthropic' but its API key is not configured`
after `secret_llm.env` was seeded with a blank `CLAUDE_API_KEY`.

## 4. Skills updated (`.claude/skills/`)

- `chatapp-page-scaffold`: removed the stale `Sample/` template references, added
  `ConfigIssues` to the page list, added a section on the config guard (new
  config/secret keys need a checker and a test).
- `aiagent-scaffold`, `root-project-scaffold`, `mcp-capability-scaffold`: notes
  that real files are auto-created from `.example` twins.

## 5. chat_app: bootstrap admin synced on every start

`ensure_bootstrap_admin` (`chat_app/src/services/auth_service.py`) used to create
the admin only when the `accounts` table was empty. An admin created before
`secret_bootstrap_admin.env` was filled in kept its old username, email and
password, so the configured credentials never worked.

Now, on every start, the protected account (`is_protected=True`) is updated from
`secret_bootstrap_admin.env`:

- username and email follow the env file. A field is skipped if another account
  already uses that value (uniqueness).
- the password hash is rewritten when the env password differs from the stored
  one. An empty `BOOTSTRAP_ADMIN_PASSWORD` leaves the existing hash alone.
- first-run creation is unchanged: it only happens when no accounts exist, and a
  random password is printed once if none is configured.
- Tests: `tests/test_bootstrap_admin.py`
  (`test_ensure_bootstrap_admin_updates_existing_admin_from_secrets_each_call`).

## Known limitations

- The tests `test_capabilities_page::test_try_tool_allowed_with_try_permission`,
  `test_chat_client::test_chat_client_behavior` and
  `test_logs_page::test_errors_tab_shows_details_for_error_entries` fail with or
  without these changes.
- `mcp_server/src/run.py` seeds secrets from the relative path `.secrets`, so it
  only works when launched from the `mcp_server` directory (as before).
- Validation covers chat_app only; ai_agent and mcp_server have no issues page.
