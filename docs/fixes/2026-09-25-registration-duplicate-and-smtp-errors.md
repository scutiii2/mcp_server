# Registration crashes: duplicate email and SMTP failure (2026-09-25)

Two unhandled exceptions surfaced as Werkzeug debugger pages (HTTP 500)
while registering a new account through `/auth/register`. Both are now
caught and turned into user-facing messages.

## 1. `IntegrityError: UNIQUE constraint failed: accounts.email`

### Symptom

Registering with an email (or username) that already belongs to an account
crashed with:

```
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) UNIQUE constraint failed: accounts.email
```

The traceback ended in `otp_service.consume_invite` -> `db_session.commit()`,
because that commit is the first flush of the new `Account` row.

### Cause

`auth_service.register_account` validated the invite code but never checked
whether the username or email was already taken. `Account.username` and
`Account.email` are `unique=True` (`chat_app/src/models/account.py`), so the database
rejected the insert and nothing above it caught the error.

### Fix

- `chat_app/src/services/auth_service.py`
  - New `RegistrationError(ValueError)` carrying a message safe to show the
    registrant.
  - `register_account` now checks for an existing username/email **after**
    the invite check and raises `RegistrationError("Username is already
    taken")` or `RegistrationError("Email is already registered")`.
  - The invite is validated first on purpose: only someone holding a valid
    invite can learn whether an account exists, which limits account
    enumeration.
  - A concurrent registration that slips past the pre-check still hits the
    constraint; that `IntegrityError` is caught, the session is rolled back
    (which also restores the invite's `used_at`), and a `RegistrationError`
    is raised.
  - Invalid/expired invites still return `None`, so existing callers and
    tests are unchanged.
- `chat_app/src/pages/Auth/__index__.py` - `register()` catches `RegistrationError`
  and re-renders `register.html` with the message (HTTP 409).

On rejection the invite is **not** consumed and no account row is created.

## 2. `ConnectionRefusedError: [WinError 10061]` on send

### Symptom

After the duplicate fix, a fresh registration crashed with:

```
ConnectionRefusedError: [WinError 10061] No connection could be made because the target machine actively refused it
```

raised from `email_service.send_email_verification` -> `mail.send(message)`.

### Cause

- **Configuration:** every field in `chat_app/secrets/secret_smtp.env` was empty, so
  `init_mail` fell back to `MAIL_SERVER=localhost`, `MAIL_PORT=587`, where
  nothing was listening.
- **Code:** no caller of `email_service` handled a send failure, so any SMTP
  problem became a 500. In `register()` the account was already committed
  before the send, so the user was left with an account but no login
  session.

### Fix

- `chat_app/src/services/email_service.py`
  - New `EmailDeliveryError(RuntimeError)`.
  - `send_invite_email` and `send_email_verification` go through a shared
    `_deliver()` that catches `smtplib.SMTPException` and `OSError` (which
    covers `ConnectionRefusedError` and timeouts), logs a warning, and raises
    `EmailDeliveryError` with a message pointing at `chat_app/secrets/secret_smtp.env`.
- `chat_app/src/pages/Auth/__index__.py`
  - `register()` logs the user in **before** sending. If the send fails it
    flashes the error and still redirects to `/auth/verify-email`, where
    "Resend code" can retry once SMTP works.
  - `resend_verification_email()` re-renders the verify page with the error
    (HTTP 503) instead of claiming "A new code was sent".
- `chat_app/src/pages/Admin/__index__.py`
  - `send_verification()` flashes the error; the audit log entry is written
    only when the send succeeds.
  - `create_invite()` with `delivery_method="email"` falls back to showing
    the one-time code for manual sharing when the send fails, so the code is
    not lost.

## Configuring SMTP

Fill in `chat_app/secrets/secret_smtp.env` (git-ignored via `chat_app/.gitignore`,
`secrets/*`) and restart chat_app - settings are read only at startup. See
`chat_app/secrets/secret_smtp.env.example` for provider host/port values.

**Gmail** (requires 2-Step Verification and an
[app password](https://myaccount.google.com/apppasswords)):

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@gmail.com
SMTP_PASSWORD=<16-char app password, no spaces>
SMTP_USE_TLS=true
MAIL_FROM_ADDRESS=you@gmail.com
```

**Local testing without real email** - run a sink that prints messages to
the console:

```bash
.\chat_app\.venv_chat\Scripts\python.exe -m pip install aiosmtpd
.\chat_app\.venv_chat\Scripts\python.exe -m aiosmtpd -n -l localhost:1025
```

```
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USE_TLS=false
MAIL_FROM_ADDRESS=noreply@localhost
```

Common Gmail failures, now shown as "Email could not be sent..." with the
detail in the log: `535 Username and Password not accepted` (wrong or
missing app password, or 2-Step Verification off); connection timeout
(port 587 blocked by network or antivirus).

## Tests

- `chat_app/tests/test_auth_service.py::test_register_account_rejects_duplicate_and_keeps_invite`
  (parametrized: duplicate username, duplicate email) - asserts the
  `RegistrationError` message, that the invite stays unused, and that no
  account is added.
- `chat_app/tests/test_email_service.py::test_send_wraps_smtp_connection_failure`
  (parametrized over both send functions).
- `chat_app/tests/test_auth_page.py::test_register_still_logs_in_when_verification_email_fails`
- `chat_app/tests/test_auth_page.py::test_resend_verification_shows_error_when_email_fails`

Full suite after the change: 550 passed, 3 failed. The 3 failures
(`test_try_tool_allowed_with_try_permission`, `test_chat_client_behavior`,
`test_errors_tab_shows_details_for_error_entries`) fail identically without
this change and are unrelated.

## PH build (`mcp_architecture_PH_20260924_235147.zip`)

The PH snapshot has both bugs: its `email_service.py`, `auth_service.py` and
`pages/Auth/__index__.py` are identical to the pre-fix `HEAD`, and its
`pages/Admin/__index__.py` differs only in the capability-labels import and
template context. It also ships no `chat_app/secrets/secret_smtp.env`. To port: copy
the three identical files over whole, apply only the two
`try/except EmailDeliveryError` blocks to `Admin/__index__.py`, and copy the
test changes.
