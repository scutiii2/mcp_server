# pages/Auth/

Merged login/registration/logout flow (spec §6, §7). URL prefix: `/auth`
(via `pages/__index__.py` auto-discovery).

## Routes

- `GET /auth/login`, `POST /auth/login` — the one application login.
  On success: verifies credentials (`auth_service.verify_credentials`),
  records a `LoginAttempt`, computes a device fingerprint and logs a
  `SecurityEvent` if it's new for the account, then issues the
  Flask-Login session and redirects to `/` (the Overview page, added in
  a later phase — until then this 404s, which is expected).
- `GET /auth/register`, `POST /auth/register` — OTP-gated registration.
  Requires a valid, unexpired, unused invite code
  (`auth_service.register_account` → `otp_service`). New accounts get
  **no roles** by default.
- `GET /auth/logout` — clears the Flask-Login session, redirects to
  `/auth/login`.

## Permissions

None — every route here is intentionally reachable without
authentication (that's the point of a login/registration page).

## Templates

`login.html` and `register.html` (not a single `view.html`, since this
page has two distinct forms) both extend `__shared__/base.html`. No
sidebar — the sidebar is for authenticated pages (added in a later
phase); this page renders standalone.
