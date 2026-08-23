# src/services/security/

The network-security pipeline (spec §9). Each module is a pure-function-
first service, independently unit tested against plain dicts, so it
works with or without a running Flask app.

- **`ip_filter.py`** - `evaluate_ip()`: allow/deny list + best-effort
  geofencing (skipped, not erroring, when no lookup DB is configured).
- **`rate_limit.py`** - `check_rate_limit()`: DB-backed brute-force
  lockout, scoped by IP and/or account, reading `LoginAttempt`.
- **`headers.py`** - `build_security_headers()` /
  `should_force_https()`: CSP, HSTS, and force-HTTPS-redirect decisions.
- **`fingerprint.py`** - `compute_fingerprint()` / `is_new_device()` /
  `record_device()`: device identification, called from
  `pages/Auth/__index__.py`'s login route to log new-device
  `SecurityEvent`s.
- **`cross_site.py`** - `check_cross_site()`: `Sec-Fetch-Site`/Origin
  check standing in for a CSRF token on routes exempted from
  Flask-WTF's CSRFProtect (Chat, Capabilities) - see its own docstring.
- **`pipeline.py`** - `load_security_configs()` /
  `register_security_pipeline()`: reads every `config_security_*.json`
  in `../../configs/` and wires `ip_filter`, `rate_limit`, and `headers`
  into `before_request`/`after_request` on the Flask app.
  `fingerprint.py` and `cross_site.py` are intentionally **not** wired
  here - `fingerprint.py` runs inside the login route handler, the only
  place that knows which account to check against; `cross_site.py` runs
  inline in each CSRF-exempt route.

## Adding a new security module

1. The module itself, following `ip_filter.py`'s shape: pure functions
   that take plain data in and return a decision, no Flask imports in
   the core logic.
2. A `config_security_<name>.json` (+ `.example`) in `../../configs/` -
   see that folder's README for the loading convention.
3. If it belongs in the standing pipeline (evaluated on every request),
   wire it into `register_security_pipeline()`. If it only applies at
   one specific route (like `fingerprint.py`/`cross_site.py`), call it
   from that route instead and leave `pipeline.py` alone.
