from werkzeug.security import check_password_hash, generate_password_hash

from src.models import Account, InviteOTP, db
from src.services import auth_service, otp_service


def test_verify_credentials_returns_account_for_correct_password(app):
    with app.app_context():
        account = Account(
            username="carol",
            email="carol@example.com",
            password_hash=generate_password_hash("correct-horse"),
        )
        db.session.add(account)
        db.session.commit()

        result = auth_service.verify_credentials(db.session, "carol", "correct-horse")

    assert result is not None
    assert result.username == "carol"


def test_verify_credentials_returns_none_for_wrong_password(app):
    with app.app_context():
        account = Account(
            username="dave",
            email="dave@example.com",
            password_hash=generate_password_hash("correct-horse"),
        )
        db.session.add(account)
        db.session.commit()

        result = auth_service.verify_credentials(db.session, "dave", "wrong-password")

    assert result is None


def test_verify_credentials_returns_none_for_unknown_username(app):
    with app.app_context():
        result = auth_service.verify_credentials(db.session, "ghost", "whatever")

    assert result is None


def test_verify_credentials_returns_none_for_inactive_account(app):
    with app.app_context():
        account = Account(
            username="erin",
            email="erin@example.com",
            password_hash=generate_password_hash("correct-horse"),
            is_active=False,
        )
        db.session.add(account)
        db.session.commit()

        result = auth_service.verify_credentials(db.session, "erin", "correct-horse")

    assert result is None


def test_record_login_attempt_persists_row(app):
    with app.app_context():
        attempt = auth_service.record_login_attempt(db.session, "203.0.113.4", None, False)

        assert attempt.id is not None
        assert attempt.success is False


def test_register_account_creates_account_and_consumes_invite(app):
    with app.app_context():
        inviter = Account(username="admin", email="admin@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, "newbie@example.com", "manual")

        account = auth_service.register_account(db.session, "newbie", "newbie@example.com", "s3cret!", code)

        assert account is not None
        assert account.username == "newbie"
        assert account.roles == []

        refreshed_invite = db.session.get(InviteOTP, invite.id)
        assert refreshed_invite.used_at is not None


def test_register_account_rejects_invalid_invite_code(app):
    with app.app_context():
        account = auth_service.register_account(db.session, "nope", "nope@example.com", "pw", "bad-code")

    assert account is None


def test_register_account_rejects_reused_invite_code(app):
    with app.app_context():
        inviter = Account(username="admin2", email="admin2@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, None, "manual")
        first = auth_service.register_account(db.session, "first", "first@example.com", "pw", code)
        second = auth_service.register_account(db.session, "second", "second@example.com", "pw", code)

    assert first is not None
    assert second is None


def test_init_login_manager_user_loader_returns_account(app):
    auth_service.init_login_manager(app)

    with app.app_context():
        account = Account(username="frank", email="frank@example.com", password_hash="hashed")
        db.session.add(account)
        db.session.commit()

        loaded = auth_service.login_manager._user_callback(str(account.id))

    assert loaded is not None
    assert loaded.username == "frank"


def test_update_account_profile_succeeds_with_correct_password(app):
    with app.app_context():
        account = Account(
            username="profile_user",
            email="old@example.com",
            password_hash=generate_password_hash("current-pw"),
        )
        db.session.add(account)
        db.session.commit()

        success = auth_service.update_account_profile(
            db.session, account, "current-pw", "new@example.com", None
        )

        assert success is True
        assert account.email == "new@example.com"


def test_update_account_profile_fails_with_wrong_password(app):
    with app.app_context():
        account = Account(
            username="profile_user2",
            email="unchanged@example.com",
            password_hash=generate_password_hash("current-pw"),
        )
        db.session.add(account)
        db.session.commit()

        success = auth_service.update_account_profile(
            db.session, account, "wrong-pw", "new@example.com", None
        )

        assert success is False
        assert account.email == "unchanged@example.com"


def test_update_account_profile_updates_password_hash(app):
    with app.app_context():
        account = Account(
            username="profile_user3",
            email="profile_user3@example.com",
            password_hash=generate_password_hash("old-pw"),
        )
        db.session.add(account)
        db.session.commit()

        auth_service.update_account_profile(db.session, account, "old-pw", None, "new-pw")

        assert check_password_hash(account.password_hash, "new-pw")
