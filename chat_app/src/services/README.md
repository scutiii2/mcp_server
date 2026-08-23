# src/services/

Business-logic services, grouped by responsibility. Route handlers stay
thin; logic that touches the DB or makes a policy decision lives here.

- `security/` — the network security pipeline (spec §9). Each module is
  a pure-function-first service, independently unit tested against plain
  dicts, so it works with or without a running Flask app:
  - `ip_filter.py` — `evaluate_ip()`: allow/deny list + best-effort
    geofencing (skipped, not erroring, when no lookup DB is configured).
  - `rate_limit.py` — `check_rate_limit()`: DB-backed brute-force
    lockout, scoped by IP and/or account, reading `LoginAttempt`.
  - `headers.py` — `build_security_headers()` / `should_force_https()`:
    CSP, HSTS, and force-HTTPS-redirect decisions.
  - `fingerprint.py` — `compute_fingerprint()` / `is_new_device()` /
    `record_device()`: device identification, called from
    `pages/Auth/__index__.py`'s login route to log new-device
    `SecurityEvent`s.
  - `pipeline.py` — `register_security_pipeline()`: wires `ip_filter`,
    `rate_limit`, and `headers` into `before_request`/`after_request`
    on the Flask app. `fingerprint.py` is intentionally **not** wired
    here — it runs inside the login route handler, which is the only
    place that knows which account to check against.
- `auth_service.py` — `login_manager` (Flask-Login singleton),
  `init_login_manager()`, `verify_credentials()`, `record_login_attempt()`,
  `register_account()`, and `ensure_bootstrap_admin()` (self-healing:
  syncs the `Administrator` role's permissions to match
  `authz.registered_permissions()` on every boot, not just first run).
- `otp_service.py` — `create_invite()`, `find_valid_invite()`,
  `consume_invite()`: the registration-gate OTP lifecycle.
- `authz.py` — `require_permission()` decorator (401 if unauthenticated,
  403 if authenticated but lacking the permission), plus
  `registered_permissions()` / `account_permissions()` / `has_permission()`.
- `email_service.py` — `mail` (Flask-Mail singleton), `init_mail()`,
  `send_invite_email()`: the auto-email delivery option for invites
  generated on the Admin page.
- `admin_service.py` — `list_roles()`, `list_accounts()`, `create_role()`,
  `assign_permission_to_role()` (validated against
  `authz.registered_permissions()`), `remove_permission_from_role()`,
  `assign_role_to_account()`, `remove_role_from_account()` (raises
  `ProtectedAccountError` for `is_protected` accounts).
- `log_service.py` — `log_action()`, `log_error()` (backs the Errors
  tab's automatic capture in `run.py`, never called manually elsewhere),
  `list_entries()` (kind + server-vs-account filter, row-capped) — all
  read/write `LogEntry`, backing the Logs page.
