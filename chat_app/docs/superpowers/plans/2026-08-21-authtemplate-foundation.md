# AuthTemplate Foundation & Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the AuthTemplate project skeleton — config/secrets loading, daily-file logging, the full SQLAlchemy data model, and a bootable Flask app factory — with nothing else wired in yet (no pages, no security pipeline, no auth flow). This is Phase 1 of a multi-phase build; later phases (security pipeline, auth core, admin/invites, pages) depend on everything here.

**Architecture:** Flask app factory (`create_app()` in `src/run.py`) that loads isolated per-topic `.env` secrets, initializes Flask-SQLAlchemy against SQLite, and creates all tables. Models live one-class-per-file under `src/models/`, wired together through `src/models/__init__.py` so SQLAlchemy's mapper registry sees every class before `db.create_all()` runs.

**Tech Stack:** Python 3.11+, Flask 3.x, Flask-SQLAlchemy 3.x, python-dotenv, pytest.

**Spec:** [docs/superpowers/specs/2026-08-21-authtemplate-design.md](../specs/2026-08-21-authtemplate-design.md)

## Global Constraints

- Folder structure follows spec §4 exactly: `src/{configs,secrets,data,logs,pages,models,services,utils}/`.
- `src/secrets/`, `src/data/`, `src/logs/` are gitignored already (see `.gitignore`); every `secret_*.env` ships a checked-in `secret_*.env.example`.
- Each `.env` file is loaded independently via `dotenv_values()` into its own dict — never merged into `os.environ` (spec §8).
- SQLite is the default DB (`src/data/app.db`), swappable via `secret_db.env`'s `DATABASE_URL` (spec §3, §14).
- Log lines are structured text: `[timestamp] LEVEL module: message`, written to `src/logs/{MM}{DD}{YYYY}.txt`, rotating automatically at midnight — no manual rotation (spec §13).
- Documentation is distributed per folder, not centralized (spec §17) — `src/models/README.md` and `src/utils/README.md` must exist and describe each file's responsibility.
- No placeholders, no TODOs — every model field in this plan matches spec §5 exactly.

---

## File Structure

```
pyproject.toml                          # deps + pytest config
src/
  __init__.py
  run.py                                # create_app() factory
  utils/
    __init__.py
    config_loader.py                    # load_json_config, load_env_secrets, load_all_json_configs
    README.md
  models/
    __init__.py                         # imports every model so mappers register
    base.py                             # db = SQLAlchemy()
    account.py
    role.py
    permission.py
    associations.py                     # account_role, role_permission tables
    invite_otp.py
    login_attempt.py
    device_fingerprint.py
    security_event.py
    README.md
  secrets/
    secret_app.env.example
    secret_db.env.example
    secret_smtp.env.example
    secret_bootstrap_admin.env.example
tests/
  conftest.py
  test_config_loader.py
  test_logging_setup.py
  test_models.py
  test_app_factory.py
```

Note: `src/utils/logging_setup.py` is created in Task 2 (listed above with utils/ but built after config_loader).

---

### Task 1: Project scaffold + config loader

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py` (empty)
- Create: `src/utils/__init__.py` (empty)
- Create: `src/utils/config_loader.py`
- Create: `src/utils/README.md`
- Test: `tests/test_config_loader.py`

**Interfaces:**
- Produces: `load_json_config(path) -> dict`, `load_env_secrets(path) -> dict`, `load_all_json_configs(configs_dir) -> dict[str, dict]` — all in `src/utils/config_loader.py`, all accepting `str | Path`.

- [ ] **Step 1: Create the project scaffold**

`pyproject.toml`:
```toml
[project]
name = "authtemplate"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "Flask>=3.0",
    "Flask-Login>=0.6",
    "Flask-Session>=0.8",
    "Flask-SQLAlchemy>=3.1",
    "Flask-WTF>=1.2",
    "Flask-Mail>=0.9",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

Create empty `src/__init__.py` and `src/utils/__init__.py`.

- [ ] **Step 2: Write the failing test**

`tests/test_config_loader.py`:
```python
import json

import pytest

from src.utils.config_loader import (
    load_all_json_configs,
    load_env_secrets,
    load_json_config,
)


def test_load_json_config_reads_file(tmp_path):
    config_file = tmp_path / "config_example.json"
    config_file.write_text(json.dumps({"enabled": True, "max": 5}))

    result = load_json_config(config_file)

    assert result == {"enabled": True, "max": 5}


def test_load_json_config_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_json_config(tmp_path / "does_not_exist.json")


def test_load_env_secrets_reads_file(tmp_path):
    env_file = tmp_path / "secret_app.env"
    env_file.write_text("SECRET_KEY=abc123\nOTHER=xyz\n")

    result = load_env_secrets(env_file)

    assert result == {"SECRET_KEY": "abc123", "OTHER": "xyz"}


def test_load_env_secrets_missing_returns_empty(tmp_path):
    result = load_env_secrets(tmp_path / "does_not_exist.env")

    assert result == {}


def test_load_all_json_configs_directory(tmp_path):
    (tmp_path / "config_a.json").write_text(json.dumps({"a": 1}))
    (tmp_path / "config_b.json").write_text(json.dumps({"b": 2}))
    (tmp_path / "not_json.txt").write_text("ignore me")

    result = load_all_json_configs(tmp_path)

    assert result == {"config_a": {"a": 1}, "config_b": {"b": 2}}


def test_load_all_json_configs_missing_dir_returns_empty(tmp_path):
    result = load_all_json_configs(tmp_path / "nope")

    assert result == {}
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_config_loader.py -v`
Expected: FAIL (or ERROR) with `ModuleNotFoundError: No module named 'src.utils.config_loader'`

- [ ] **Step 4: Implement `config_loader.py`**

`src/utils/config_loader.py`:
```python
import json
from pathlib import Path

from dotenv import dotenv_values


def load_json_config(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_env_secrets(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    return dict(dotenv_values(path))


def load_all_json_configs(configs_dir: str | Path) -> dict[str, dict]:
    configs_dir = Path(configs_dir)
    if not configs_dir.exists():
        return {}
    return {file.stem: load_json_config(file) for file in sorted(configs_dir.glob("*.json"))}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_config_loader.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Write `src/utils/README.md`**

```markdown
# src/utils/

Small, single-purpose helper modules used across the app.

- `config_loader.py` — loads `src/configs/*.json` feature-toggle files
  and `src/secrets/*.env` credential files. Each `.env` is loaded into
  its own isolated dict via `dotenv_values()` (never merged into
  `os.environ`), so secret topics stay independent.
- `logging_setup.py` — daily-rotating file logger factory; every
  service calls `get_logger(__name__)` to get a logger that writes to
  `src/logs/{MM}{DD}{YYYY}.txt`.
- `tokens.py` — OTP/random token generation and hashing (added in a
  later phase).
- `validators.py` — input validation helpers (added in a later phase).
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/__init__.py src/utils/__init__.py src/utils/config_loader.py src/utils/README.md tests/test_config_loader.py
git commit -m "feat: add project scaffold and config/secrets loader"
```

---

### Task 2: Daily-file logging

**Files:**
- Create: `src/utils/logging_setup.py`
- Test: `tests/test_logging_setup.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `get_logger(name: str, logs_dir: str | Path = "src/logs") -> logging.Logger`, `DailyFileHandler` class with `.current_log_path() -> Path`.

- [ ] **Step 1: Write the failing test**

`tests/test_logging_setup.py`:
```python
import logging
from datetime import datetime

from src.utils.logging_setup import DailyFileHandler, get_logger


def test_current_log_path_uses_mmddyyyy_format(tmp_path):
    handler = DailyFileHandler(tmp_path)

    expected_name = f"{datetime.now():%m%d%Y}.txt"

    assert handler.current_log_path() == tmp_path / expected_name


def test_get_logger_writes_structured_line_to_dated_file(tmp_path):
    logger = get_logger("test.module.one", logs_dir=str(tmp_path))

    logger.info("hello world")

    expected_file = tmp_path / f"{datetime.now():%m%d%Y}.txt"
    assert expected_file.exists()
    content = expected_file.read_text(encoding="utf-8")
    assert "INFO" in content
    assert "test.module.one" in content
    assert "hello world" in content


def test_get_logger_does_not_duplicate_handlers_on_repeat_calls(tmp_path):
    logger_a = get_logger("test.module.two", logs_dir=str(tmp_path))
    logger_b = get_logger("test.module.two", logs_dir=str(tmp_path))

    assert logger_a is logger_b
    daily_handlers = [h for h in logger_a.handlers if isinstance(h, DailyFileHandler)]
    assert len(daily_handlers) == 1


def test_get_logger_sets_info_level(tmp_path):
    logger = get_logger("test.module.three", logs_dir=str(tmp_path))

    assert logger.level == logging.INFO
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_logging_setup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.utils.logging_setup'`

- [ ] **Step 3: Implement `logging_setup.py`**

`src/utils/logging_setup.py`:
```python
import logging
from datetime import datetime
from pathlib import Path

_LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class DailyFileHandler(logging.Handler):
    def __init__(self, logs_dir: str | Path):
        super().__init__()
        self.logs_dir = Path(logs_dir)

    def current_log_path(self) -> Path:
        return self.logs_dir / f"{datetime.now():%m%d%Y}.txt"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            message = self.format(record)
            with self.current_log_path().open("a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception:
            self.handleError(record)


def get_logger(name: str, logs_dir: str | Path = "src/logs") -> logging.Logger:
    logger = logging.getLogger(name)
    logs_dir = Path(logs_dir)
    has_handler = any(
        isinstance(h, DailyFileHandler) and h.logs_dir == logs_dir for h in logger.handlers
    )
    if not has_handler:
        handler = DailyFileHandler(logs_dir)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_logging_setup.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/utils/logging_setup.py tests/test_logging_setup.py
git commit -m "feat: add daily-rotating file logger factory"
```

---

### Task 3: Base, associations, Account, Role, Permission models

**Files:**
- Create: `src/models/__init__.py`
- Create: `src/models/base.py`
- Create: `src/models/associations.py`
- Create: `src/models/account.py`
- Create: `src/models/role.py`
- Create: `src/models/permission.py`
- Test: `tests/conftest.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `db` (Flask-SQLAlchemy instance) in `src/models/base.py`; `account_role`/`role_permission` tables in `src/models/associations.py`; `Account` (id, username, email, password_hash, is_protected, is_active, created_at, relationship `roles`); `Role` (id, name, description, relationships `accounts`, `permissions`); `Permission` (id, name, description, relationship `roles`).
- Later tasks (4, 5) import `db` and these classes from `src/models`.
- Note: `Account.roles` and `Role.accounts` reference each other by string name in a M2M relationship, so `Account`, `Role`, and `Permission` must all be defined and imported into `src/models/__init__.py` together before any mapper can be configured — that's why they're one task, not three.

- [ ] **Step 1: Create `base.py` and `associations.py`**

`src/models/base.py`:
```python
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
```

`src/models/associations.py`:
```python
from src.models.base import db

account_role = db.Table(
    "account_roles",
    db.Column("account_id", db.Integer, db.ForeignKey("accounts.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
)

role_permission = db.Table(
    "role_permissions",
    db.Column("role_id", db.Integer, db.ForeignKey("roles.id"), primary_key=True),
    db.Column("permission_id", db.Integer, db.ForeignKey("permissions.id"), primary_key=True),
)
```

- [ ] **Step 2: Create `account.py`, `role.py`, `permission.py`**

`src/models/account.py`:
```python
from datetime import datetime, timezone

from src.models.associations import account_role
from src.models.base import db


class Account(db.Model):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_protected = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    roles = db.relationship("Role", secondary=account_role, back_populates="accounts")
```

`src/models/role.py`:
```python
from src.models.associations import account_role, role_permission
from src.models.base import db


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    accounts = db.relationship("Account", secondary=account_role, back_populates="roles")
    permissions = db.relationship("Permission", secondary=role_permission, back_populates="roles")
```

`src/models/permission.py`:
```python
from src.models.associations import role_permission
from src.models.base import db


class Permission(db.Model):
    __tablename__ = "permissions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)

    roles = db.relationship("Role", secondary=role_permission, back_populates="permissions")
```

- [ ] **Step 3: Create `src/models/__init__.py`**

```python
from src.models.account import Account
from src.models.associations import account_role, role_permission
from src.models.base import db
from src.models.permission import Permission
from src.models.role import Role

__all__ = ["db", "Account", "Role", "Permission", "account_role", "role_permission"]
```

- [ ] **Step 4: Write the failing test**

`tests/conftest.py`:
```python
import pytest
from flask import Flask

from src.models import db


@pytest.fixture
def app(tmp_path):
    application = Flask(__name__)
    db_path = tmp_path / "test.db"
    application.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    application.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    application.config["TESTING"] = True

    db.init_app(application)
    with application.app_context():
        db.create_all()

    yield application

    with application.app_context():
        db.session.remove()
        db.drop_all()
```

`tests/test_models.py`:
```python
from src.models import Account, Permission, Role, db


def test_create_account(app):
    with app.app_context():
        account = Account(
            username="alice",
            email="alice@example.com",
            password_hash="hashed",
        )
        db.session.add(account)
        db.session.commit()

        fetched = db.session.get(Account, account.id)
        assert fetched.username == "alice"
        assert fetched.email == "alice@example.com"
        assert fetched.is_protected is False
        assert fetched.is_active is True
        assert fetched.created_at is not None
        assert fetched.roles == []


def test_create_role_and_permission_with_m2m_relationship(app):
    with app.app_context():
        role = Role(name="editor", description="Can edit content")
        permission = Permission(name="account.edit", description="Edit own account")
        role.permissions.append(permission)
        db.session.add(role)
        db.session.commit()

        fetched_role = db.session.query(Role).filter_by(name="editor").one()
        assert [p.name for p in fetched_role.permissions] == ["account.edit"]
        assert [r.name for r in permission.roles] == ["editor"]


def test_account_role_m2m_relationship(app):
    with app.app_context():
        account = Account(username="bob", email="bob@example.com", password_hash="hashed")
        role = Role(name="viewer", description="Read-only")
        account.roles.append(role)
        db.session.add(account)
        db.session.commit()

        fetched_account = db.session.query(Account).filter_by(username="bob").one()
        assert [r.name for r in fetched_account.roles] == ["viewer"]
        assert [a.username for a in role.accounts] == ["bob"]
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.models'`

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/models/base.py src/models/associations.py src/models/account.py src/models/role.py src/models/permission.py src/models/__init__.py tests/conftest.py tests/test_models.py
git commit -m "feat: add Account, Role, Permission models with M2M relationships"
```

---

### Task 4: InviteOTP, LoginAttempt, DeviceFingerprint, SecurityEvent + models README

**Files:**
- Create: `src/models/invite_otp.py`
- Create: `src/models/login_attempt.py`
- Create: `src/models/device_fingerprint.py`
- Create: `src/models/security_event.py`
- Create: `src/models/README.md`
- Modify: `src/models/__init__.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Consumes: `db` from `src/models/base`, `Account` for foreign keys.
- Produces: `InviteOTP`, `LoginAttempt`, `DeviceFingerprint`, `SecurityEvent` — exact fields per spec §5.

- [ ] **Step 1: Create the four model files**

`src/models/invite_otp.py`:
```python
from datetime import datetime, timezone

from src.models.base import db


class InviteOTP(db.Model):
    __tablename__ = "invite_otps"

    id = db.Column(db.Integer, primary_key=True)
    code_hash = db.Column(db.String(255), nullable=False)
    created_by_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    invitee_email = db.Column(db.String(255), nullable=True)
    delivery_method = db.Column(db.String(20), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship("Account", foreign_keys=[created_by_account_id])
```

`src/models/login_attempt.py`:
```python
from datetime import datetime, timezone

from src.models.base import db


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"

    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(45), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
    success = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    account = db.relationship("Account", foreign_keys=[account_id])
```

`src/models/device_fingerprint.py`:
```python
from datetime import datetime, timezone

from src.models.base import db


class DeviceFingerprint(db.Model):
    __tablename__ = "device_fingerprints"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    fingerprint_hash = db.Column(db.String(128), nullable=False)
    first_seen_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    account = db.relationship("Account", foreign_keys=[account_id])
```

`src/models/security_event.py`:
```python
from datetime import datetime, timezone

from src.models.base import db


class SecurityEvent(db.Model):
    __tablename__ = "security_events"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
    event_type = db.Column(db.String(50), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    details = db.Column(db.String(500), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    account = db.relationship("Account", foreign_keys=[account_id])
```

- [ ] **Step 2: Update `src/models/__init__.py`**

```python
from src.models.account import Account
from src.models.associations import account_role, role_permission
from src.models.base import db
from src.models.device_fingerprint import DeviceFingerprint
from src.models.invite_otp import InviteOTP
from src.models.login_attempt import LoginAttempt
from src.models.permission import Permission
from src.models.role import Role
from src.models.security_event import SecurityEvent

__all__ = [
    "db",
    "Account",
    "Role",
    "Permission",
    "account_role",
    "role_permission",
    "InviteOTP",
    "LoginAttempt",
    "DeviceFingerprint",
    "SecurityEvent",
]
```

- [ ] **Step 3: Write the failing tests**

Append to `tests/test_models.py`:
```python
from datetime import datetime, timedelta, timezone

from src.models import DeviceFingerprint, InviteOTP, LoginAttempt, SecurityEvent


def test_create_invite_otp(app):
    with app.app_context():
        inviter = Account(username="admin", email="admin@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite = InviteOTP(
            code_hash="hashedcode",
            created_by_account_id=inviter.id,
            invitee_email="new@example.com",
            delivery_method="email",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        db.session.add(invite)
        db.session.commit()

        fetched = db.session.get(InviteOTP, invite.id)
        assert fetched.delivery_method == "email"
        assert fetched.used_at is None
        assert fetched.created_by.username == "admin"


def test_create_login_attempt(app):
    with app.app_context():
        attempt = LoginAttempt(ip_address="203.0.113.4", account_id=None, success=False)
        db.session.add(attempt)
        db.session.commit()

        fetched = db.session.get(LoginAttempt, attempt.id)
        assert fetched.success is False
        assert fetched.account_id is None


def test_create_device_fingerprint(app):
    with app.app_context():
        account = Account(username="carol", email="carol@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        fp = DeviceFingerprint(account_id=account.id, fingerprint_hash="abcd1234")
        db.session.add(fp)
        db.session.commit()

        fetched = db.session.get(DeviceFingerprint, fp.id)
        assert fetched.account.username == "carol"
        assert fetched.fingerprint_hash == "abcd1234"


def test_create_security_event(app):
    with app.app_context():
        event = SecurityEvent(
            account_id=None,
            event_type="ip_blocked",
            ip_address="198.51.100.7",
            details="deny-list match",
        )
        db.session.add(event)
        db.session.commit()

        fetched = db.session.get(SecurityEvent, event.id)
        assert fetched.event_type == "ip_blocked"
        assert fetched.details == "deny-list match"
```

- [ ] **Step 4: Run the tests to verify they fail then pass**

Run: `pytest tests/test_models.py -v`
Expected first (before implementation existed): collection error / `ImportError`. After Step 1-2 implementation: PASS (7 tests total).

- [ ] **Step 5: Write `src/models/README.md`**

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
git add src/models/invite_otp.py src/models/login_attempt.py src/models/device_fingerprint.py src/models/security_event.py src/models/__init__.py src/models/README.md tests/test_models.py
git commit -m "feat: add InviteOTP, LoginAttempt, DeviceFingerprint, SecurityEvent models"
```

---

### Task 5: App factory + secret example files

**Files:**
- Create: `src/run.py`
- Create: `src/secrets/secret_app.env.example`
- Create: `src/secrets/secret_db.env.example`
- Create: `src/secrets/secret_smtp.env.example`
- Create: `src/secrets/secret_bootstrap_admin.env.example`
- Test: `tests/test_app_factory.py`

**Interfaces:**
- Consumes: `db` and all models from `src/models`; `load_env_secrets` from `src/utils/config_loader`.
- Produces: `create_app(config: dict | None = None) -> Flask` in `src/run.py`. Later phases (security pipeline, pages) will extend this factory — do not change its signature.

- [ ] **Step 1: Write the secret example files**

`src/secrets/secret_app.env.example`:
```
# Flask session/signing key. Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=
```

`src/secrets/secret_db.env.example`:
```
# Leave empty to default to SQLite at src/data/app.db.
# Example for Postgres: DATABASE_URL=postgresql://user:pass@localhost:5432/authtemplate
DATABASE_URL=
```

`src/secrets/secret_smtp.env.example`:
```
# Used by src/services/email_service.py for auto-emailed invite OTPs (added in a later phase).
SMTP_HOST=
SMTP_PORT=
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_USE_TLS=true
MAIL_FROM_ADDRESS=
```

`src/secrets/secret_bootstrap_admin.env.example`:
```
# Optional. If unset, a random bootstrap admin password is generated and
# printed to the console once on first run (added in a later phase).
BOOTSTRAP_ADMIN_USERNAME=
BOOTSTRAP_ADMIN_EMAIL=
BOOTSTRAP_ADMIN_PASSWORD=
```

- [ ] **Step 2: Write the failing test**

`tests/test_app_factory.py`:
```python
from flask import Flask

from src.models import Account, db
from src.run import create_app


def test_create_app_returns_flask_app(tmp_path):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "TESTING": True,
    })

    assert isinstance(app, Flask)
    assert app.config["SQLALCHEMY_DATABASE_URI"] == f"sqlite:///{tmp_path / 'test.db'}"


def test_create_app_initializes_tables(tmp_path):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "TESTING": True,
    })

    with app.app_context():
        account = Account(username="dave", email="dave@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        fetched = db.session.query(Account).filter_by(username="dave").one()
        assert fetched.email == "dave@example.com"


def test_create_app_has_secret_key_set(tmp_path):
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "TESTING": True,
    })

    assert app.config["SECRET_KEY"]
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_app_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.run'`

- [ ] **Step 4: Implement `src/run.py`**

```python
from pathlib import Path

from flask import Flask

from src.models import db
from src.utils.config_loader import load_env_secrets

BASE_DIR = Path(__file__).resolve().parent


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)

    app_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_app.env")
    db_secrets = load_env_secrets(BASE_DIR / "secrets" / "secret_db.env")

    app.config["SECRET_KEY"] = app_secrets.get("SECRET_KEY") or "dev-insecure-key-change-me"
    app.config["SQLALCHEMY_DATABASE_URI"] = db_secrets.get("DATABASE_URL") or (
        f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if config:
        app.config.update(config)

    db.init_app(app)

    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=True)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_app_factory.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests across Tasks 1-6 — config loader, logging, models, app factory)

- [ ] **Step 7: Commit**

```bash
git add src/run.py src/secrets/secret_app.env.example src/secrets/secret_db.env.example src/secrets/secret_smtp.env.example src/secrets/secret_bootstrap_admin.env.example tests/test_app_factory.py
git commit -m "feat: add create_app factory wiring config/secrets and db init"
```

---

## Out of Scope for This Plan (later phases)

- Security pipeline (`src/services/security/*`, `src/configs/config_security_*.json`) — Phase 2.
- `auth_service`, `otp_service`, `authz.py`, `tokens.py`, bootstrap admin creation, error handlers — Phase 3.
- `admin_service`, `email_service`, Admin page — Phase 4.
- `pages/__index__.py` auto-discovery, `__shared__/` layout, Overview and Account pages — Phase 5.
- Root README and remaining per-folder READMEs (`src/pages/README.md`, `src/services/README.md`) — Phase 6, once those folders have real content.
