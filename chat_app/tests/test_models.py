from datetime import datetime, timedelta, timezone

from src.models import (
    Account,
    DeviceFingerprint,
    InviteOTP,
    LogEntry,
    LoginAttempt,
    Permission,
    Role,
    SecurityEvent,
    db,
)


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


def test_create_log_entry(app):
    with app.app_context():
        account = Account(username="logowner", email="logowner@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        action_entry = LogEntry(
            kind="action",
            account_id=account.id,
            source="test.source",
            message="did a thing",
        )
        error_entry = LogEntry(
            kind="error",
            account_id=None,
            source="unhandled_exception",
            message="boom",
            details="Traceback (most recent call last): ...",
        )
        db.session.add_all([action_entry, error_entry])
        db.session.commit()

        fetched_action = db.session.get(LogEntry, action_entry.id)
        assert fetched_action.kind == "action"
        assert fetched_action.account.username == "logowner"
        assert fetched_action.details is None
        assert fetched_action.created_at is not None

        fetched_error = db.session.get(LogEntry, error_entry.id)
        assert fetched_error.kind == "error"
        assert fetched_error.account_id is None
        assert fetched_error.details == "Traceback (most recent call last): ..."
