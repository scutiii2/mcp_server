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
