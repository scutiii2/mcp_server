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
