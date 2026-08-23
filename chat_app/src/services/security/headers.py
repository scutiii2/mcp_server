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
