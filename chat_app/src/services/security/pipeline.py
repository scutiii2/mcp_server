from flask import Flask, abort, redirect, request
from flask_wtf import CSRFProtect

from src.models import db
from src.services.security.cross_site import check_cross_site
from src.services.security.headers import build_security_headers, should_force_https
from src.services.security.ip_filter import evaluate_ip
from src.services.security.rate_limit import check_rate_limit
from src.utils.config_loader import load_all_json_configs


def load_security_configs(configs_dir) -> dict:
    return load_all_json_configs(configs_dir)


def register_security_pipeline(app: Flask, configs: dict) -> CSRFProtect | None:
    ip_filter_config = configs.get("config_security_ip_filter", {"enabled": False})
    rate_limit_config = configs.get("config_security_rate_limit", {"enabled": False})
    headers_config = configs.get("config_security_headers", {"enabled": False})

    csrf_extension = None
    if headers_config.get("enabled", False) and headers_config.get("csrf_enabled", False):
        csrf_extension = CSRFProtect(app)

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

        check_cross_site()

    @app.after_request
    def _security_pipeline_after_request(response):
        for header, value in build_security_headers(headers_config).items():
            response.headers[header] = value
        return response

    return csrf_extension
