# src/models/

SQLAlchemy models, one file per table. All import `db` from `base.py`.
`__init__.py` imports every model module so SQLAlchemy's mapper
registry can resolve string-based relationship references before
`db.create_all()` runs — always add new models to both the model file
and `__init__.py`.

- `base.py` — the shared `db = SQLAlchemy()` instance.
- `account.py` — `Account`: the single application account (id,
  username, email, password_hash, is_protected, is_active, created_at).
- `role.py` — `Role`: named, configurable bundle of permissions.
- `permission.py` — `Permission`: namespaced string (`"<page>.<action>"`).
- `associations.py` — `account_role`, `role_permission` M2M tables.
- `invite_otp.py` — `InviteOTP`: single-use, time-limited registration
  gate.
- `login_attempt.py` — `LoginAttempt`: backs rate-limiting/lockout.
- `device_fingerprint.py` — `DeviceFingerprint`: known devices per
  account.
- `security_event.py` — `SecurityEvent`: audit trail (lockouts, new
  devices, IP blocks, ...).
- `log_entry.py` — `LogEntry`: backs the Logs page (`kind`: `action`
  or `error`, `account_id` nullable — `NULL` means "server"), written
  by `services/log_service.py`.
