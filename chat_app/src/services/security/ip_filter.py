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
