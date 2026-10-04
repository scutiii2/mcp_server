# pages/ConfigIssues/

Lists problems in `configs/*.json` and `secrets/*.env`. URL prefix: `/configissues`.

## Routes

- `GET /configissues/` — table of file / key / problem. Re-reads on each load
  (cached by file mtime), so fixing a file and reloading clears it.

## Behaviour

`services/config_validation.py` validates every chat_app config and secret
(unreadable file, bad JSON, missing or mistyped key, placeholder value) and
installs a `before_request` guard: while any issue exists, every route except
this page, static files and `/internal/*` redirects here. The guard is off
when `TESTING` is set.

## Permissions

The route is open (no login) because a broken config can make login unusable.
Messages never include secret values. `config.issues.view` only controls the
nav link.

## Adding a rule

Add a checker to `_JSON_CHECKS` / `_ENV_CHECKS` in `services/config_validation.py`.
