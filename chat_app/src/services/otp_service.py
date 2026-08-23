from datetime import datetime, timedelta, timezone

from src.models import InviteOTP
from src.utils.tokens import generate_otp_code, hash_token, verify_token

OTP_EXPIRY_MINUTES = 15


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_invite(
    db_session, created_by_account_id: int, invitee_email: str | None, delivery_method: str
) -> tuple[InviteOTP, str]:
    code = generate_otp_code()
    invite = InviteOTP(
        code_hash=hash_token(code),
        created_by_account_id=created_by_account_id,
        invitee_email=invitee_email,
        delivery_method=delivery_method,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES),
    )
    db_session.add(invite)
    db_session.commit()
    return invite, code


def find_valid_invite(db_session, code: str) -> InviteOTP | None:
    now = datetime.now(timezone.utc)
    candidates = db_session.query(InviteOTP).filter(InviteOTP.used_at.is_(None)).all()
    for candidate in candidates:
        if verify_token(code, candidate.code_hash) and _as_utc(candidate.expires_at) > now:
            return candidate
    return None


def consume_invite(db_session, invite: InviteOTP) -> None:
    invite.used_at = datetime.now(timezone.utc)
    db_session.commit()


def delete_invite(db_session, invite: InviteOTP) -> None:
    db_session.delete(invite)
    db_session.commit()
