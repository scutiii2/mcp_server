# AuthTemplate — Design Spec

Date: 2026-08-21
Status: Draft — pending user review

## 1. Goals

Build a reusable Flask template that merges **network-level security**
(rate limiting, IP filtering, security headers, device fingerprinting)
directly into a single **application login** — there is only one
account and one login flow; the security layer wraps it rather than
requiring separate credentials. Registration is invite-only: an
existing account with the right permission generates a short-lived,
single-use OTP that gates account creation. Accounts can hold multiple
roles; roles hold permissions scoped per page *and* per action.

## 2. Non-Goals

- No login-time 2FA/OTP — OTP is a registration gate only.
- No multi-tenant support.
- No built-in production deployment tooling (WSGI server, Docker,
  etc.) — this is an app-level template, not an ops template.
- No hard dependency on an external IP-geolocation service — country
  geofencing is best-effort/pluggable, not guaranteed available.

## 3. Architecture Overview

Flask app factory (`src/run.py`) initializes, in order:

1. Load `src/configs/*.json` (feature toggles/tuning) and
   `src/secrets/*.env` (credentials/keys — gitignored).
2. Init SQLAlchemy (SQLite by default, swappable via `secret_db.env`).
3. Init Flask-Login (auth/session plumbing) + Flask-Session
   (server-side, DB-backed session store).
4. Install the network-security pipeline as `before_request` /
   `after_request` hooks (`src/services/security/pipeline.py`).
5. Auto-discover and register every page blueprint under `src/pages/`.

## 4. Folder Structure

```
AuthTemplate/
  README.md                        # project overview, links to folder READMEs
  src/
    run.py
    configs/
      config_security_rate_limit.json
      config_security_ip_filter.json
      config_security_headers.json
      config_security_fingerprint.json
    secrets/                      # gitignored; *.env.example shipped
      secret_app.env              # Flask session/signing key
      secret_db.env               # DB connection info (if not sqlite)
      secret_smtp.env             # SMTP creds for auto-email OTP delivery
      secret_bootstrap_admin.env  # optional preset bootstrap admin creds
    data/                         # gitignored; all runtime-generated data
      app.db                      # SQLite DB (accounts, roles, sessions, ...)
    logs/                         # gitignored; one file per calendar day
      08212026.txt                # MMDDYYYY.txt, e.g. today's log
    pages/
      README.md                   # page-folder convention + index of pages
      __index__.py                # auto-discovers + registers blueprints
      __shared__/
        README.md                 # what the shared layout/sidebar provide
        base.html                 # base layout: head, sidebar/topbar includes
        sidebar.html              # partial: nav + user/logout footer
        shared.js
        shared.css
      Overview/
        README.md                 # this page's purpose, routes, permissions
        __index__.py              # blueprint, prefix "/"
        view.html
        script.js
        style.css
      Auth/
        README.md                 # this page's purpose, routes, permissions
        __index__.py              # prefix "/auth": /login /logout /register
        view.html
        script.js
        style.css
      Account/
        README.md                 # this page's purpose, routes, permissions
        __index__.py              # prefix "/account": profile mgmt
        view.html
        script.js
        style.css
      Admin/
        README.md                 # this page's purpose, routes, permissions
        __index__.py              # prefix "/admin": roles/permissions/invites
        view.html
        script.js
        style.css
    models/
      README.md                   # what each model file represents
      base.py                     # SQLAlchemy declarative base + db init
      account.py
      role.py
      permission.py
      associations.py             # AccountRole, RolePermission join tables
      invite_otp.py
      login_attempt.py
      device_fingerprint.py
      security_event.py
    services/
      README.md                   # what each service is responsible for
      auth_service.py             # credential check, session issuance
      otp_service.py               # OTP generation/validation, expiry/use
      authz.py                     # @require_permission, permission resolution
      email_service.py             # OTP email delivery (Flask-Mail)
      admin_service.py             # role/permission/account admin operations
      security/
        pipeline.py                # orchestrates the 4 checks below, in order
        rate_limit.py
        ip_filter.py
        headers.py
        fingerprint.py
    utils/
      README.md                   # what each utility helper does
      config_loader.py             # loads/validates configs (JSON) + secrets (.env)
      tokens.py                    # OTP/random token generation, hashing
      validators.py
      logging_setup.py             # daily-file logger factory
```

## 5. Data Model

- **Account** — id, username, email, password_hash, `is_protected`
  (true only for the bootstrap admin; blocks deletion and role
  stripping), is_active, created_at
- **Role** — id, name, description
- **Permission** — id, name (namespaced string, e.g. `"account.edit"`,
  `"admin.roles.manage"`, `"auth.invite"`), description
- **AccountRole** — account_id, role_id (M2M: account ↔ role)
- **RolePermission** — role_id, permission_id (M2M: role ↔ permission)
- **InviteOTP** — id, code_hash, created_by_account_id, invitee_email
  (nullable), delivery_method (`email` | `manual`), expires_at
  (created_at + 15 min), used_at (nullable, single-use)
- **LoginAttempt** — id, ip_address, account_id (nullable), success,
  created_at — backs rate-limiting/lockout (DB-backed, per decision)
- **DeviceFingerprint** — id, account_id, fingerprint_hash,
  first_seen_at, last_seen_at
- **SecurityEvent** — id, account_id (nullable), event_type
  (`lockout`, `new_device`, `ip_blocked`, ...), ip_address, details,
  created_at — audit trail

Permissions are namespaced strings (`"<page>.<action>"`) rather than
normalized Page/Action tables — a new page just declares the
permission strings it checks for; no schema migration needed to add a
permission.

## 6. One Merged Login

There is exactly one `Account` and one login endpoint
(`POST /auth/login`) — no separate "network security account." The
security pipeline wraps that same request/response cycle:

1. **Pre-route pipeline**: IP allow/deny check → rate-limit/lockout
   check (by IP and/or account, per config) → security headers /
   CSRF / HTTPS enforcement.
2. **Route handler**: verify credentials → record a `LoginAttempt` →
   compute a device fingerprint (hash of User-Agent + Accept-Language
   + IP/24 subnet) and log a `SecurityEvent` if it's new for this
   account → Flask-Login issues the server-side session cookie
   (secure, httponly, samesite).

Brute-force lockout, fingerprinting, and the credential check all
happen inside this single flow — never a separate auth step.

## 7. OTP-Gated Registration

- Only accounts holding the `auth.invite` permission can generate an
  invite (from the Admin page's Invites section).
- Inviter picks delivery per invite: auto-email (via
  `secret_smtp.json` + `email_service.py`) or shown on-screen to copy
  and share manually — both supported, chosen per invite.
- OTP: random code, hashed at rest (`tokens.py`), expires in 15
  minutes, single-use — rejected after expiry or after first
  successful registration.
- Registering with a valid OTP creates the `Account` with **no roles
  assigned by default**; an admin assigns roles afterward from the
  Admin page.

## 8. Bootstrap Admin & Secrets

- On first run, if the accounts table is empty, the app auto-creates
  one `is_protected` admin account holding every permission. It
  cannot be deleted and its role/permission set cannot be stripped.
- Credentials come from `secret_bootstrap_admin.env` if present;
  otherwise a random password is generated and printed to the console
  once (never stored in plaintext after that).
- `src/secrets/` holds one `.env` file per topic (see folder structure
  above), each loaded independently via `python-dotenv`'s
  `dotenv_values()` (kept in its own dict, not merged into
  `os.environ`, so topics stay isolated) — all gitignored, each with a
  checked-in `*.env.example` showing the expected keys.

## 9. Network Security Pipeline (`src/configs/`)

Four independently toggleable config files, each with an `enabled`
flag; pipeline runs cheapest-reject-first:

1. `config_security_ip_filter.json` — allow list, deny list, optional
   country geofencing (best-effort via a pluggable offline lookup;
   if no lookup DB is configured, geofencing rules are skipped rather
   than erroring, IP allow/deny still applies).
2. `config_security_rate_limit.json` — max attempts, time window,
   lockout duration, scope (`ip`, `account`, or `both`). Implemented
   as a small custom service reading `LoginAttempt`, not Flask-Limiter
   (which doesn't naturally back onto the app DB).
3. `config_security_headers.json` — CSP, HSTS max-age, force-HTTPS
   redirect, CSRF settings (via Flask-WTF).
4. `config_security_fingerprint.json` — which request signals to hash,
   new-device behavior (log-only vs. flash a warning), trust
   duration.

## 10. Roles & Permissions Enforcement

Each page declares the permissions its routes require via a
`@require_permission("account.edit")` decorator (`services/authz.py`),
checked against the union of permissions across all of the current
account's roles. The **Admin page** (`pages/Admin/`, itself gated
behind `admin.roles.manage`) is where roles are created, permissions
assigned to roles, roles assigned to accounts, and invites generated.

## 11. Pages, Routing & Shared Layout

- `pages/__index__.py` auto-discovers each subfolder (excluding
  `__shared__`), imports its `__index__.py`, expects a `blueprint`
  attribute, and registers it with a URL prefix derived from the
  lowercased folder name (`Account` → `/account`, `Admin` → `/admin`,
  `Overview` → `/`).
- `pages/__shared__/` (not auto-registered) holds the base Jinja
  layout and the sidebar partial, included by every page's
  `view.html`.

## 12. Overview Page & Navigation

- **Overview** (`pages/Overview/`, served at `/`) is the post-login
  landing page. It shows a tile/link for every page the current
  account has permission to reach (computed by checking each
  registered blueprint's declared permission requirement against the
  account's permission set).
- Because Overview already serves as the page picker, the **sidebar
  is hidden there**. Instead, Overview shows the logged-in account
  (username) plus a **Logout** option in the **upper-right corner**.
- On every *other* page, an **expandable/collapsible sidebar** is
  shown instead, listing the same permitted pages as nav links, with
  the logged-in account and a **Logout** option pinned at the bottom.

## 13. Logging (`src/logs/`)

Every meaningful step is logged, not just errors: incoming requests,
each security-pipeline decision (IP allow/deny, rate-limit check,
header/CSRF enforcement, fingerprint result), auth flow steps (login
attempt, success/failure, lockout, logout), OTP lifecycle (generated,
emailed, viewed, used, expired-attempt), and admin actions (role
created/edited, permission assigned, account role changed).

- `utils/logging_setup.py` configures a standard Python `logging`
  logger whose handler picks the target file dynamically: on each
  write it resolves to `src/logs/{MM}{DD}{YYYY}.txt` for the current
  date (e.g. `08212026.txt`), opening a new file automatically at
  midnight — no manual rotation needed.
- Every service (`auth_service`, `otp_service`, `security/*`,
  `admin_service`) gets this logger via `logging.getLogger(__name__)`
  and logs at the appropriate level (`INFO` for normal steps, `WARNING`
  for lockouts/blocks, `ERROR` for unexpected failures).
- Log lines are structured text: timestamp, level, module, message
  (e.g. `[2026-08-21 14:03:11] INFO auth_service: login success
  account_id=12 ip=203.0.113.4`).
- `src/logs/` is gitignored (runtime-generated, grows daily).

## 14. Data Storage (`src/data/`)

All runtime-generated application data lives under `src/data/`, kept
separate from source, configs, and secrets:

- `src/data/app.db` — the SQLite database (accounts, roles,
  permissions, invites, login attempts, fingerprints, security
  events, server-side sessions). `secret_db.json` defaults to this
  path; swapping to Postgres/MySQL just changes the connection string.
- Any future runtime-generated files (exports, uploaded assets, etc.)
  also live under `src/data/`, in their own subfolder.
- `src/data/` is gitignored, same as `src/secrets/` and `src/logs/`.

## 15. Error Handling

- 401 → redirect to `/auth/login` (unauthenticated)
- 403 → permission-denied page (authenticated, lacks permission)
- 429 → rate-limited page (from the security pipeline)
- Consistent styled error pages sharing the base layout.

## 16. Testing Strategy

pytest with fixtures for: an in-memory/temp-file SQLite DB per test,
a factory for accounts/roles/permissions, and a test client with the
security pipeline configurable per-test (so rate-limit/IP tests don't
interfere with unrelated auth tests). Not built as part of this spec
— covered by the implementation plan.

## 17. Documentation Structure (READMEs)

Documentation is distributed, not centralized, so it stays correct as
this template is cloned and extended in future projects — pieces that
move with their code, rather than a single README that goes stale.

- **Root `README.md`** — project overview, setup/run instructions, and
  the security/auth model *in the abstract*: what a permission is
  (namespaced `"<page>.<action>"` string), what a role is (a named,
  configurable bundle of permissions), and how registration/OTP/roles
  interact. It does **not** name specific roles (e.g. no hardcoded
  "Admin"/"Member" list) and does **not** describe individual pages —
  both are project-specific and page-specific respectively, and would
  go stale as pages are added/removed per project. Instead it links
  out to `src/pages/README.md`, `src/models/README.md`,
  `src/services/README.md`, and `src/utils/README.md`.
- **`src/pages/README.md`** — explains the page-folder convention
  (blueprint auto-discovery, URL-prefix-from-folder-name, the
  `__shared__/` layout) and keeps a short index linking to each
  page's own README. Adding a new page in a future project means
  adding one line here, not rewriting this file's content.
- **Each page's own `README.md`** (e.g. `src/pages/Auth/README.md`) —
  self-contained: that page's purpose, its routes, the permission(s)
  it requires, and any page-specific notes. Since each page folder is
  the unit that gets copied into future projects, its documentation
  travels with it.
- **`src/models/README.md`, `src/services/README.md`,
  `src/utils/README.md`** — one per folder, describing what each file
  inside is responsible for, following the same one-file/one-purpose
  pattern as the code itself.

## 18. Defaults Flagged for Review

These were reasonable defaults chosen during design, not explicitly
requested — flag now if any should change:

- Password hashing: Werkzeug's built-in `generate_password_hash`
  (scrypt) — zero extra dependency, swappable later.
- New registrations get **no roles** by default (admin assigns
  roles afterward) rather than an automatic baseline role.
- Invite generation lives on the **Admin** page, not the Account page.
- Sessions: Flask-Session with a SQLAlchemy (DB) backend.
- CSRF: Flask-WTF.
- Email delivery: Flask-Mail for the auto-email OTP option.
- Log level granularity (INFO for routine steps) — say if you want
  quieter default logging with more verbosity behind a debug flag.
