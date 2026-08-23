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
