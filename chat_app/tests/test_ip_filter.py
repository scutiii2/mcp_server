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
