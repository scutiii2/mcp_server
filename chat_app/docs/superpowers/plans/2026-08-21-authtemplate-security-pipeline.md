# AuthTemplate Security Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the network-level security pipeline — IP allow/deny + best-effort geofencing, DB-backed rate limiting/lockout, security response headers + CSRF, and device fingerprinting — as independently toggleable, independently testable services, then wire the IP filter, rate limiter, and headers into the Flask app as global `before_request`/`after_request` hooks. This is Phase 2 of a multi-phase build, depending on the models and app factory from Phase 1 ([2026-08-21-authtemplate-foundation.md](2026-08-21-authtemplate-foundation.md)).

**Architecture:** Each of the four checks (`ip_filter`, `rate_limit`, `headers`, `fingerprint`) is a small, pure-function-first service module under `src/services/security/`, independently unit tested against plain dicts (no Flask app needed). `pipeline.py` loads the four JSON configs and wires `ip_filter` + `rate_limit` + `headers` into `before_request`/`after_request` on the Flask app (cheapest-reject-first: force-HTTPS redirect → IP check → rate-limit check, then headers applied on the way out). `fingerprint.py` is deliberately **not** wired into the generic pipeline — per spec §6, fingerprinting happens inside the login route handler (Phase 3), which needs to know *which account* to check against. Its compute/lookup functions are built and fully tested here so Phase 3 just calls them.

**Tech Stack:** Flask (`before_request`/`after_request`), Flask-WTF (`CSRFProtect`), Python's `ipaddress` stdlib module, `hashlib` (SHA-256 fingerprint hashing), pytest, Flask's test client for pipeline integration tests.

**Spec:** [docs/superpowers/specs/2026-08-21-authtemplate-design.md](../specs/2026-08-21-authtemplate-design.md)

## Global Constraints

- Four independently toggleable config files, each with an `enabled` flag (spec §9); pipeline runs cheapest-reject-first.
- No hard dependency on an external IP-geolocation service (spec §2, §9): if `geofencing.lookup_db_path` is unset or no `country_lookup` callable is supplied, geofencing is skipped rather than erroring — IP allow/deny still applies.
- Rate limiting is a small custom service reading the `LoginAttempt` table (spec §9) — not Flask-Limiter, which doesn't naturally back onto the app DB.
- CSRF via Flask-WTF (spec §8 defaults, §9).
- Fingerprint hash inputs: User-Agent + Accept-Language + IP/24 subnet (spec §6).
- All stored timestamps are UTC; SQLite round-trips `db.DateTime` columns as **naive** datetimes (no `timezone=True` on the columns per Phase 1), so any code comparing a freshly-read timestamp against `datetime.now(timezone.utc)` must treat naive values as UTC.
- Documentation is distributed per folder (spec §17) — `src/services/README.md` must exist and describe each file's responsibility.
- No placeholders, no TODOs.

---

## File Structure

```
src/
  configs/
    config_security_ip_filter.json
    config_security_rate_limit.json
    config_security_headers.json
    config_security_fingerprint.json
  services/
    __init__.py
    README.md
    security/
      __init__.py
      ip_filter.py        # check_ip_lists, check_geofencing, evaluate_ip
      rate_limit.py        # RateLimitResult, check_rate_limit
      headers.py            # build_security_headers, should_force_https
      fingerprint.py        # compute_fingerprint, is_new_device, record_device
      pipeline.py            # load_security_configs, register_security_pipeline
  run.py                       # MODIFIED: wires register_security_pipeline into create_app
tests/
  test_ip_filter.py
  test_rate_limit.py
  test_headers.py
  test_fingerprint.py
  test_pipeline.py
```

---

### Task 1: Security configs + IP filter service

**Files:**
- Create: `src/configs/config_security_ip_filter.json`
- Create: `src/configs/config_security_rate_limit.json`
- Create: `src/configs/config_security_headers.json`
- Create: `src/configs/config_security_fingerprint.json`
- Create: `src/services/__init__.py` (empty)
- Create: `src/services/security/__init__.py` (empty)
- Create: `src/services/security/ip_filter.py`
- Test: `tests/test_ip_filter.py`

**Interfaces:**
- Produces: `check_ip_lists(config: dict, ip_address: str) -> tuple[bool, str | None]`, `check_geofencing(config: dict, ip_address: str, country_lookup=None) -> tuple[bool, str | None]`, `evaluate_ip(config: dict, ip_address: str, country_lookup=None) -> tuple[bool, str | None]` in `src/services/security/ip_filter.py`.
- Later tasks: Task 5 (`pipeline.py`) imports `evaluate_ip`.

- [ ] **Step 1: Write the four config JSON files**

`src/configs/config_security_ip_filter.json`:
```json
{
  "enabled": true,
  "allow_list": [],
  "deny_list": [],
  "geofencing": {
    "enabled": false,
    "allowed_countries": [],
    "lookup_db_path": null
  }
}
```

`src/configs/config_security_rate_limit.json`:
```json
{
  "enabled": true,
  "max_attempts": 5,
  "window_seconds": 300,
  "lockout_seconds": 900,
  "scope": "both"
}
```

`src/configs/config_security_headers.json`:
```json
{
  "enabled": true,
  "content_security_policy": "default-src 'self'",
  "hsts_max_age": 31536000,
  "force_https": false,
  "csrf_enabled": true
}
```

`src/configs/config_security_fingerprint.json`:
```json
{
  "enabled": true,
  "signals": ["user_agent", "accept_language", "ip_subnet"],
  "new_device_behavior": "log_only",
  "trust_duration_days": 30
}
```

Create empty `src/services/__init__.py` and `src/services/security/__init__.py`.

- [ ] **Step 2: Write the failing test**

`tests/test_ip_filter.py`:
```python
from src.services.security.ip_filter import check_geofencing, check_ip_lists, evaluate_ip


def test_check_ip_lists_blocks_denied_ip():
    config = {"deny_list": ["203.0.113.4"], "allow_list": []}

    allowed, reason = check_ip_lists(config, "203.0.113.4")

    assert allowed is False
    assert reason == "ip_denied"


def test_check_ip_lists_blocks_denied_cidr():
    config = {"deny_list": ["203.0.113.0/24"], "allow_list": []}

    allowed, reason = check_ip_lists(config, "203.0.113.99")

    assert allowed is False
    assert reason == "ip_denied"


def test_check_ip_lists_allows_when_no_lists():
    config = {"deny_list": [], "allow_list": []}

    allowed, reason = check_ip_lists(config, "198.51.100.1")

    assert allowed is True
    assert reason is None


def test_check_ip_lists_allow_list_restricts_access():
    config = {"deny_list": [], "allow_list": ["10.0.0.0/8"]}

    denied_allowed, denied_reason = check_ip_lists(config, "198.51.100.1")
    permitted_allowed, permitted_reason = check_ip_lists(config, "10.1.2.3")

    assert denied_allowed is False
    assert denied_reason == "ip_not_allowed"
    assert permitted_allowed is True
    assert permitted_reason is None


def test_check_geofencing_disabled_allows():
    config = {"geofencing": {"enabled": False}}

    allowed, reason = check_geofencing(config, "198.51.100.1")

    assert allowed is True
    assert reason is None


def test_check_geofencing_enabled_without_lookup_db_allows():
    config = {"geofencing": {"enabled": True, "lookup_db_path": None, "allowed_countries": ["US"]}}

    allowed, reason = check_geofencing(config, "198.51.100.1", country_lookup=lambda ip: "RU")

    assert allowed is True
    assert reason is None


def test_check_geofencing_blocks_disallowed_country():
    config = {
        "geofencing": {
            "enabled": True,
            "lookup_db_path": "/fake/path.mmdb",
            "allowed_countries": ["US"],
        }
    }

    allowed, reason = check_geofencing(config, "198.51.100.1", country_lookup=lambda ip: "RU")

    assert allowed is False
    assert reason == "country_blocked"


def test_check_geofencing_allows_matching_country():
    config = {
        "geofencing": {
            "enabled": True,
            "lookup_db_path": "/fake/path.mmdb",
            "allowed_countries": ["US"],
        }
    }

    allowed, reason = check_geofencing(config, "198.51.100.1", country_lookup=lambda ip: "US")

    assert allowed is True
    assert reason is None


def test_evaluate_ip_disabled_config_allows_everything():
    config = {"enabled": False, "deny_list": ["198.51.100.1"], "allow_list": []}

    allowed, reason = evaluate_ip(config, "198.51.100.1")

    assert allowed is True
    assert reason is None


def test_evaluate_ip_short_circuits_before_geofencing_lookup():
    calls = []

    def spy_lookup(ip):
        calls.append(ip)
        return "US"

    config = {
        "enabled": True,
        "deny_list": ["198.51.100.1"],
        "allow_list": [],
        "geofencing": {"enabled": True, "lookup_db_path": "/fake.mmdb", "allowed_countries": ["US"]},
    }

    allowed, reason = evaluate_ip(config, "198.51.100.1", country_lookup=spy_lookup)

    assert allowed is False
    assert reason == "ip_denied"
    assert calls == []


def test_evaluate_ip_runs_geofencing_when_ip_lists_pass():
    config = {
        "enabled": True,
        "deny_list": [],
        "allow_list": [],
        "geofencing": {"enabled": True, "lookup_db_path": "/fake.mmdb", "allowed_countries": ["US"]},
    }

    allowed, reason = evaluate_ip(config, "198.51.100.1", country_lookup=lambda ip: "RU")

    assert allowed is False
    assert reason == "country_blocked"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_ip_filter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services'`

- [ ] **Step 4: Implement `ip_filter.py`**

`src/services/security/ip_filter.py`:
```python
import ipaddress


def _ip_matches(ip_address: str, entries: list[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip_address)
    except ValueError:
        return False

    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if addr in network:
            return True
    return False


def check_ip_lists(config: dict, ip_address: str) -> tuple[bool, str | None]:
    deny_list = config.get("deny_list", [])
    if _ip_matches(ip_address, deny_list):
        return False, "ip_denied"

    allow_list = config.get("allow_list", [])
    if allow_list and not _ip_matches(ip_address, allow_list):
        return False, "ip_not_allowed"

    return True, None


def check_geofencing(config: dict, ip_address: str, country_lookup=None) -> tuple[bool, str | None]:
    geo_config = config.get("geofencing", {})
    if not geo_config.get("enabled", False):
        return True, None

    lookup_db_path = geo_config.get("lookup_db_path")
    if not lookup_db_path or country_lookup is None:
        return True, None

    country_code = country_lookup(ip_address)
    if not country_code:
        return True, None

    allowed_countries = geo_config.get("allowed_countries", [])
    if allowed_countries and country_code not in allowed_countries:
        return False, "country_blocked"

    return True, None


def evaluate_ip(config: dict, ip_address: str, country_lookup=None) -> tuple[bool, str | None]:
    if not config.get("enabled", False):
        return True, None

    allowed, reason = check_ip_lists(config, ip_address)
    if not allowed:
        return allowed, reason

    return check_geofencing(config, ip_address, country_lookup=country_lookup)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_ip_filter.py -v`
Expected: PASS (12 tests)

- [ ] **Step 6: Commit**

```bash
git add src/configs/config_security_ip_filter.json src/configs/config_security_rate_limit.json src/configs/config_security_headers.json src/configs/config_security_fingerprint.json src/services/__init__.py src/services/security/__init__.py src/services/security/ip_filter.py tests/test_ip_filter.py
git commit -m "feat: add security configs and IP allow/deny + geofencing filter"
```

---

### Task 2: Rate limit service

**Files:**
- Create: `src/services/security/rate_limit.py`
- Test: `tests/test_rate_limit.py`

**Interfaces:**
- Consumes: `LoginAttempt`, `Account`, `db` from `src.models` (Phase 1).
- Produces: `RateLimitResult` dataclass (`allowed: bool`, `retry_after_seconds: int | None = None`, `reason: str | None = None`), `check_rate_limit(config: dict, db_session, ip_address: str, account_id: int | None = None) -> RateLimitResult` in `src/services/security/rate_limit.py`.
- Later tasks: Task 5 (`pipeline.py`) imports `check_rate_limit`.

- [ ] **Step 1: Write the failing test**

`tests/test_rate_limit.py`:
```python
from datetime import datetime, timedelta, timezone

from src.models import Account, LoginAttempt, db
from src.services.security.rate_limit import check_rate_limit


def _failed_attempt(ip_address=None, account_id=None, minutes_ago=0):
    return LoginAttempt(
        ip_address=ip_address or "203.0.113.4",
        account_id=account_id,
        success=False,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


def test_check_rate_limit_disabled_always_allows(app):
    config = {"enabled": False}

    with app.app_context():
        result = check_rate_limit(config, db.session, "203.0.113.4")

    assert result.allowed is True


def test_check_rate_limit_allows_when_under_threshold(app):
    config = {
        "enabled": True,
        "max_attempts": 5,
        "window_seconds": 300,
        "lockout_seconds": 900,
        "scope": "ip",
    }

    with app.app_context():
        for _ in range(3):
            db.session.add(_failed_attempt(ip_address="203.0.113.4"))
        db.session.commit()

        result = check_rate_limit(config, db.session, "203.0.113.4")

    assert result.allowed is True


def test_check_rate_limit_blocks_when_threshold_reached(app):
    config = {
        "enabled": True,
        "max_attempts": 3,
        "window_seconds": 300,
        "lockout_seconds": 900,
        "scope": "ip",
    }

    with app.app_context():
        for _ in range(3):
            db.session.add(_failed_attempt(ip_address="203.0.113.4"))
        db.session.commit()

        result = check_rate_limit(config, db.session, "203.0.113.4")

    assert result.allowed is False
    assert result.reason == "rate_limited"
    assert result.retry_after_seconds > 0


def test_check_rate_limit_ignores_attempts_outside_window(app):
    config = {
        "enabled": True,
        "max_attempts": 2,
        "window_seconds": 60,
        "lockout_seconds": 900,
        "scope": "ip",
    }

    with app.app_context():
        db.session.add(_failed_attempt(ip_address="203.0.113.4", minutes_ago=10))
        db.session.add(_failed_attempt(ip_address="203.0.113.4", minutes_ago=10))
        db.session.commit()

        result = check_rate_limit(config, db.session, "203.0.113.4")

    assert result.allowed is True


def test_check_rate_limit_unlocks_after_lockout_expires(app):
    config = {
        "enabled": True,
        "max_attempts": 2,
        "window_seconds": 3600,
        "lockout_seconds": 60,
        "scope": "ip",
    }

    with app.app_context():
        db.session.add(_failed_attempt(ip_address="203.0.113.4", minutes_ago=5))
        db.session.add(_failed_attempt(ip_address="203.0.113.4", minutes_ago=5))
        db.session.commit()

        result = check_rate_limit(config, db.session, "203.0.113.4")

    assert result.allowed is True


def test_check_rate_limit_scope_account_counts_regardless_of_ip(app):
    config = {
        "enabled": True,
        "max_attempts": 2,
        "window_seconds": 300,
        "lockout_seconds": 900,
        "scope": "account",
    }

    with app.app_context():
        account = Account(username="eve", email="eve@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        db.session.add(_failed_attempt(ip_address="1.1.1.1", account_id=account.id))
        db.session.add(_failed_attempt(ip_address="2.2.2.2", account_id=account.id))
        db.session.commit()

        result = check_rate_limit(config, db.session, "9.9.9.9", account_id=account.id)

    assert result.allowed is False
    assert result.reason == "rate_limited"


def test_check_rate_limit_scope_ip_ignores_account_scope(app):
    config = {
        "enabled": True,
        "max_attempts": 2,
        "window_seconds": 300,
        "lockout_seconds": 900,
        "scope": "ip",
    }

    with app.app_context():
        account = Account(username="frank", email="frank@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        db.session.add(_failed_attempt(ip_address="1.1.1.1", account_id=account.id))
        db.session.add(_failed_attempt(ip_address="1.1.1.1", account_id=account.id))
        db.session.commit()

        result = check_rate_limit(config, db.session, "1.1.1.1")

    assert result.allowed is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_rate_limit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.security.rate_limit'`

- [ ] **Step 3: Implement `rate_limit.py`**

`src/services/security/rate_limit.py`:
```python
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from src.models import LoginAttempt


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int | None = None
    reason: str | None = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _recent_failed_attempts(db_session, since, ip_address=None, account_id=None):
    query = db_session.query(LoginAttempt).filter(
        LoginAttempt.success.is_(False),
        LoginAttempt.created_at >= since,
    )
    filters = []
    if ip_address is not None:
        filters.append(LoginAttempt.ip_address == ip_address)
    if account_id is not None:
        filters.append(LoginAttempt.account_id == account_id)
    if filters:
        query = query.filter(or_(*filters))
    return query.order_by(LoginAttempt.created_at.desc()).all()


def check_rate_limit(
    config: dict, db_session, ip_address: str, account_id: int | None = None
) -> RateLimitResult:
    if not config.get("enabled", False):
        return RateLimitResult(allowed=True)

    scope = config.get("scope", "both")
    scoped_ip = ip_address if scope in ("ip", "both") else None
    scoped_account = account_id if scope in ("account", "both") else None

    if scoped_ip is None and scoped_account is None:
        return RateLimitResult(allowed=True)

    max_attempts = config["max_attempts"]
    window_seconds = config["window_seconds"]
    lockout_seconds = config["lockout_seconds"]

    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=window_seconds)

    attempts = _recent_failed_attempts(
        db_session, since, ip_address=scoped_ip, account_id=scoped_account
    )

    if len(attempts) < max_attempts:
        return RateLimitResult(allowed=True)

    most_recent = _as_utc(attempts[0].created_at)
    lockout_ends_at = most_recent + timedelta(seconds=lockout_seconds)

    if now >= lockout_ends_at:
        return RateLimitResult(allowed=True)

    retry_after = int((lockout_ends_at - now).total_seconds())
    return RateLimitResult(allowed=False, retry_after_seconds=retry_after, reason="rate_limited")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_rate_limit.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/security/rate_limit.py tests/test_rate_limit.py
git commit -m "feat: add DB-backed rate limit/lockout service"
```

---

### Task 3: Security headers service

**Files:**
- Create: `src/services/security/headers.py`
- Test: `tests/test_headers.py`

**Interfaces:**
- Produces: `build_security_headers(config: dict) -> dict[str, str]`, `should_force_https(config: dict) -> bool` in `src/services/security/headers.py`.
- Later tasks: Task 5 (`pipeline.py`) imports both.

- [ ] **Step 1: Write the failing test**

`tests/test_headers.py`:
```python
from src.services.security.headers import build_security_headers, should_force_https


def test_build_security_headers_disabled_returns_empty():
    assert build_security_headers({"enabled": False}) == {}


def test_build_security_headers_includes_csp_and_hsts():
    config = {
        "enabled": True,
        "content_security_policy": "default-src 'self'",
        "hsts_max_age": 63072000,
    }

    headers = build_security_headers(config)

    assert headers["Content-Security-Policy"] == "default-src 'self'"
    assert headers["Strict-Transport-Security"] == "max-age=63072000; includeSubDomains"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"


def test_build_security_headers_omits_missing_optional_fields():
    config = {"enabled": True}

    headers = build_security_headers(config)

    assert "Content-Security-Policy" not in headers
    assert "Strict-Transport-Security" not in headers
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_should_force_https_true_when_enabled_and_configured():
    assert should_force_https({"enabled": True, "force_https": True}) is True


def test_should_force_https_false_when_disabled():
    assert should_force_https({"enabled": False, "force_https": True}) is False


def test_should_force_https_false_when_not_configured():
    assert should_force_https({"enabled": True, "force_https": False}) is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_headers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.security.headers'`

- [ ] **Step 3: Implement `headers.py`**

`src/services/security/headers.py`:
```python
def build_security_headers(config: dict) -> dict[str, str]:
    if not config.get("enabled", False):
        return {}

    headers: dict[str, str] = {}

    csp = config.get("content_security_policy")
    if csp:
        headers["Content-Security-Policy"] = csp

    hsts_max_age = config.get("hsts_max_age")
    if hsts_max_age:
        headers["Strict-Transport-Security"] = f"max-age={hsts_max_age}; includeSubDomains"

    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"

    return headers


def should_force_https(config: dict) -> bool:
    return bool(config.get("enabled", False) and config.get("force_https", False))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_headers.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/security/headers.py tests/test_headers.py
git commit -m "feat: add security response headers service"
```

---

### Task 4: Device fingerprint service

**Files:**
- Create: `src/services/security/fingerprint.py`
- Test: `tests/test_fingerprint.py`

**Interfaces:**
- Consumes: `DeviceFingerprint`, `Account`, `db` from `src.models` (Phase 1).
- Produces: `compute_fingerprint(config: dict, user_agent: str, accept_language: str, ip_address: str) -> str`, `is_new_device(db_session, account_id: int, fingerprint_hash: str) -> bool`, `record_device(db_session, account_id: int, fingerprint_hash: str) -> DeviceFingerprint` in `src/services/security/fingerprint.py`.
- Phase 3's `auth_service` will call all three during the login route to log `SecurityEvent` on new devices — not wired here.

- [ ] **Step 1: Write the failing test**

`tests/test_fingerprint.py`:
```python
from src.models import Account, DeviceFingerprint, db
from src.services.security.fingerprint import compute_fingerprint, is_new_device, record_device


def test_compute_fingerprint_is_deterministic():
    config = {"signals": ["user_agent", "accept_language", "ip_subnet"]}

    first = compute_fingerprint(config, "Mozilla/5.0", "en-US", "203.0.113.4")
    second = compute_fingerprint(config, "Mozilla/5.0", "en-US", "203.0.113.4")

    assert first == second
    assert len(first) == 64


def test_compute_fingerprint_differs_for_different_user_agent():
    config = {"signals": ["user_agent", "accept_language", "ip_subnet"]}

    first = compute_fingerprint(config, "Mozilla/5.0", "en-US", "203.0.113.4")
    second = compute_fingerprint(config, "Chrome/120.0", "en-US", "203.0.113.4")

    assert first != second


def test_compute_fingerprint_uses_ip_slash24_subnet_not_full_ip():
    config = {"signals": ["ip_subnet"]}

    first = compute_fingerprint(config, "", "", "203.0.113.4")
    second = compute_fingerprint(config, "", "", "203.0.113.250")

    assert first == second


def test_compute_fingerprint_only_uses_configured_signals():
    config = {"signals": ["user_agent"]}

    first = compute_fingerprint(config, "Mozilla/5.0", "en-US", "203.0.113.4")
    second = compute_fingerprint(config, "Mozilla/5.0", "fr-FR", "198.51.100.9")

    assert first == second


def test_is_new_device_true_when_never_seen(app):
    with app.app_context():
        account = Account(username="grace", email="grace@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        assert is_new_device(db.session, account.id, "abc123") is True


def test_is_new_device_false_after_record_device(app):
    with app.app_context():
        account = Account(username="heidi", email="heidi@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        record_device(db.session, account.id, "abc123")

        assert is_new_device(db.session, account.id, "abc123") is False


def test_record_device_updates_last_seen_on_repeat(app):
    with app.app_context():
        account = Account(username="ivan", email="ivan@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        first = record_device(db.session, account.id, "abc123")
        first_seen = first.first_seen_at
        record_device(db.session, account.id, "abc123")

        count = db.session.query(DeviceFingerprint).filter_by(account_id=account.id).count()
        assert count == 1

        refreshed = db.session.query(DeviceFingerprint).filter_by(account_id=account.id).one()
        assert refreshed.first_seen_at == first_seen
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_fingerprint.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.security.fingerprint'`

- [ ] **Step 3: Implement `fingerprint.py`**

`src/services/security/fingerprint.py`:
```python
import hashlib
from datetime import datetime, timezone

from src.models import DeviceFingerprint


def _subnet_24(ip_address: str) -> str:
    parts = ip_address.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0/24"
    return ip_address


def compute_fingerprint(config: dict, user_agent: str, accept_language: str, ip_address: str) -> str:
    signals = config.get("signals", ["user_agent", "accept_language", "ip_subnet"])
    values = {
        "user_agent": user_agent or "",
        "accept_language": accept_language or "",
        "ip_subnet": _subnet_24(ip_address or ""),
    }
    raw = "|".join(values.get(signal, "") for signal in signals)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_new_device(db_session, account_id: int, fingerprint_hash: str) -> bool:
    existing = (
        db_session.query(DeviceFingerprint)
        .filter_by(account_id=account_id, fingerprint_hash=fingerprint_hash)
        .first()
    )
    return existing is None


def record_device(db_session, account_id: int, fingerprint_hash: str) -> DeviceFingerprint:
    now = datetime.now(timezone.utc)
    existing = (
        db_session.query(DeviceFingerprint)
        .filter_by(account_id=account_id, fingerprint_hash=fingerprint_hash)
        .first()
    )
    if existing:
        existing.last_seen_at = now
        db_session.commit()
        return existing

    device = DeviceFingerprint(
        account_id=account_id,
        fingerprint_hash=fingerprint_hash,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(device)
    db_session.commit()
    return device
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_fingerprint.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add src/services/security/fingerprint.py tests/test_fingerprint.py
git commit -m "feat: add device fingerprint compute/lookup service"
```

---

### Task 5: Pipeline orchestration + app factory wiring

**Files:**
- Create: `src/services/security/pipeline.py`
- Modify: `src/run.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `evaluate_ip` (Task 1), `check_rate_limit` (Task 2), `build_security_headers`/`should_force_https` (Task 3), `load_all_json_configs` from `src.utils.config_loader` (Phase 1), `db` from `src.models` (Phase 1).
- Produces: `load_security_configs(configs_dir) -> dict[str, dict]`, `register_security_pipeline(app: Flask, configs: dict[str, dict]) -> None` in `src/services/security/pipeline.py`. `create_app()` in `src/run.py` calls both — its signature (`create_app(config: dict | None = None) -> Flask`) does not change.

- [ ] **Step 1: Write the failing test**

`tests/test_pipeline.py`:
```python
from datetime import datetime, timezone

from flask import Flask

from src.models import LoginAttempt, db
from src.services.security.pipeline import register_security_pipeline


def _build_test_app(tmp_path, ip_filter_config=None, rate_limit_config=None, headers_config=None):
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'pipeline_test.db'}"
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret"
    db.init_app(app)
    with app.app_context():
        db.create_all()

    @app.route("/ping")
    def ping():
        return "pong"

    configs = {
        "config_security_ip_filter": ip_filter_config or {"enabled": False},
        "config_security_rate_limit": rate_limit_config or {"enabled": False},
        "config_security_headers": headers_config or {"enabled": False},
    }
    register_security_pipeline(app, configs)
    return app


def test_pipeline_allows_request_when_all_checks_disabled(tmp_path):
    app = _build_test_app(tmp_path)
    client = app.test_client()

    response = client.get("/ping")

    assert response.status_code == 200
    assert response.data == b"pong"


def test_pipeline_blocks_denied_ip(tmp_path):
    app = _build_test_app(
        tmp_path,
        ip_filter_config={
            "enabled": True,
            "deny_list": ["127.0.0.1"],
            "allow_list": [],
            "geofencing": {"enabled": False},
        },
    )
    client = app.test_client()

    response = client.get("/ping")

    assert response.status_code == 403


def test_pipeline_applies_security_headers(tmp_path):
    app = _build_test_app(
        tmp_path,
        headers_config={
            "enabled": True,
            "content_security_policy": "default-src 'self'",
            "hsts_max_age": 63072000,
            "force_https": False,
            "csrf_enabled": False,
        },
    )
    client = app.test_client()

    response = client.get("/ping")

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_pipeline_rate_limits_after_threshold(tmp_path):
    app = _build_test_app(
        tmp_path,
        rate_limit_config={
            "enabled": True,
            "max_attempts": 2,
            "window_seconds": 300,
            "lockout_seconds": 900,
            "scope": "ip",
        },
    )

    with app.app_context():
        for _ in range(2):
            db.session.add(
                LoginAttempt(
                    ip_address="127.0.0.1",
                    account_id=None,
                    success=False,
                    created_at=datetime.now(timezone.utc),
                )
            )
        db.session.commit()

    client = app.test_client()
    response = client.get("/ping")

    assert response.status_code == 429


def test_pipeline_enables_csrf_protection_when_configured(tmp_path):
    app = _build_test_app(
        tmp_path,
        headers_config={
            "enabled": True,
            "content_security_policy": None,
            "hsts_max_age": None,
            "force_https": False,
            "csrf_enabled": True,
        },
    )

    assert app.extensions.get("csrf") is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.services.security.pipeline'`

- [ ] **Step 3: Implement `pipeline.py`**

`src/services/security/pipeline.py`:
```python
from flask import Flask, abort, redirect, request
from flask_wtf import CSRFProtect

from src.models import db
from src.services.security.headers import build_security_headers, should_force_https
from src.services.security.ip_filter import evaluate_ip
from src.services.security.rate_limit import check_rate_limit
from src.utils.config_loader import load_all_json_configs


def load_security_configs(configs_dir) -> dict:
    return load_all_json_configs(configs_dir)


def register_security_pipeline(app: Flask, configs: dict) -> None:
    ip_filter_config = configs.get("config_security_ip_filter", {"enabled": False})
    rate_limit_config = configs.get("config_security_rate_limit", {"enabled": False})
    headers_config = configs.get("config_security_headers", {"enabled": False})

    if headers_config.get("enabled", False) and headers_config.get("csrf_enabled", False):
        CSRFProtect(app)

    @app.before_request
    def _security_pipeline_before_request():
        ip_address = request.remote_addr or "unknown"

        if should_force_https(headers_config) and not request.is_secure:
            forced_url = request.url.replace("http://", "https://", 1)
            return redirect(forced_url, code=301)

        allowed, reason = evaluate_ip(ip_filter_config, ip_address)
        if not allowed:
            abort(403, description=reason)

        result = check_rate_limit(rate_limit_config, db.session, ip_address)
        if not result.allowed:
            abort(429, description=result.reason)

    @app.after_request
    def _security_pipeline_after_request(response):
        for header, value in build_security_headers(headers_config).items():
            response.headers[header] = value
        return response
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Wire the pipeline into `create_app`**

Modify `src/run.py` (Phase 1 version) to load and register the security pipeline. Full replacement content:

```python
from pathlib import Path

from flask import Flask

from src.models import db
from src.services.security.pipeline import load_security_configs, register_security_pipeline
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

    security_configs = load_security_configs(BASE_DIR / "configs")
    register_security_pipeline(app, security_configs)

    return app


if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=True)
```

- [ ] **Step 6: Run the full test suite (Phase 1 + Phase 2)**

Run: `pytest -v`
Expected: PASS (all tests from Phase 1 plus this plan's Tasks 1-5 — Phase 1's `test_create_app_*` tests now also exercise the pipeline being registered, since `create_app` loads `src/configs/*.json` on every call)

- [ ] **Step 7: Commit**

```bash
git add src/services/security/pipeline.py src/run.py tests/test_pipeline.py
git commit -m "feat: orchestrate security pipeline as before/after_request hooks"
```

---

### Task 6: Services README

**Files:**
- Create: `src/services/README.md`

**Interfaces:**
- None — documentation only.

- [ ] **Step 1: Write `src/services/README.md`**

```markdown
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
    `record_device()`: device identification, used by `auth_service`
    during login (added in a later phase) to log new-device
    `SecurityEvent`s.
  - `pipeline.py` — `register_security_pipeline()`: wires `ip_filter`,
    `rate_limit`, and `headers` into `before_request`/`after_request`
    on the Flask app. `fingerprint.py` is intentionally **not** wired
    here — it runs inside the login route handler, which is the only
    place that knows which account to check against.
- `auth_service.py` — credential check, session issuance (added in a
  later phase).
- `otp_service.py` — OTP generation/validation, expiry/use (added in a
  later phase).
- `authz.py` — `@require_permission` decorator, permission resolution
  (added in a later phase).
- `email_service.py` — OTP email delivery via Flask-Mail (added in a
  later phase).
- `admin_service.py` — role/permission/account admin operations (added
  in a later phase).
```

- [ ] **Step 2: Commit**

```bash
git add src/services/README.md
git commit -m "docs: add services folder README"
```

---

## Out of Scope for This Plan (later phases)

- Calling `compute_fingerprint`/`is_new_device`/`record_device` from an actual login route, and logging the resulting `SecurityEvent` — Phase 3 (`auth_service`).
- `otp_service`, `authz.py`, `tokens.py`, bootstrap admin creation, 401/403/429 error pages (spec §15) — Phase 3.
- `admin_service`, `email_service`, Admin page — Phase 4.
- `pages/__index__.py` auto-discovery, `__shared__/` layout, Overview and Account pages — Phase 5.
- Root README and remaining per-folder READMEs (`src/pages/README.md`) — Phase 6.
