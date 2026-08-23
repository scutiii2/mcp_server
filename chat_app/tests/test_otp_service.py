from datetime import datetime, timedelta, timezone

from src.models import Account, InviteOTP, db
from src.services import otp_service


def test_create_invite_persists_hashed_code_and_returns_plaintext(app):
    with app.app_context():
        inviter = Account(username="admin", email="admin@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, "new@example.com", "email")

        assert invite.id is not None
        assert invite.code_hash != code
        assert invite.used_at is None
        assert invite.delivery_method == "email"


def test_find_valid_invite_matches_correct_code(app):
    with app.app_context():
        inviter = Account(username="admin2", email="admin2@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, None, "manual")

        found = otp_service.find_valid_invite(db.session, code)

    assert found is not None
    assert found.id == invite.id


def test_find_valid_invite_rejects_wrong_code(app):
    with app.app_context():
        inviter = Account(username="admin3", email="admin3@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        otp_service.create_invite(db.session, inviter.id, None, "manual")

        found = otp_service.find_valid_invite(db.session, "totally-wrong-code")

    assert found is None


def test_find_valid_invite_rejects_expired_code(app):
    with app.app_context():
        inviter = Account(username="admin4", email="admin4@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, None, "manual")
        invite.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()

        found = otp_service.find_valid_invite(db.session, code)

    assert found is None


def test_find_valid_invite_rejects_used_code(app):
    with app.app_context():
        inviter = Account(username="admin5", email="admin5@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, code = otp_service.create_invite(db.session, inviter.id, None, "manual")
        otp_service.consume_invite(db.session, invite)

        found = otp_service.find_valid_invite(db.session, code)

    assert found is None


def test_consume_invite_sets_used_at(app):
    with app.app_context():
        inviter = Account(username="admin6", email="admin6@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, _ = otp_service.create_invite(db.session, inviter.id, None, "manual")
        otp_service.consume_invite(db.session, invite)

        refreshed = db.session.get(InviteOTP, invite.id)

    assert refreshed.used_at is not None


def test_delete_invite_removes_it(app):
    with app.app_context():
        inviter = Account(username="admin7", email="admin7@example.com", password_hash="hashed")
        db.session.add(inviter)
        db.session.commit()

        invite, _ = otp_service.create_invite(db.session, inviter.id, None, "manual")
        invite_id = invite.id

        otp_service.delete_invite(db.session, invite)

    with app.app_context():
        assert db.session.get(InviteOTP, invite_id) is None
