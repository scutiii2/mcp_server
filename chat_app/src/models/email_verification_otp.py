from datetime import datetime, timezone

from src.models.base import db


class EmailVerificationOtp(db.Model):
    """A one-time code proving an account controls the inbox at its
    registered email address. Same shape as InviteOTP - hashed code,
    expiry, single use - but scoped to one account rather than an
    open invitation."""

    __tablename__ = "email_verification_otps"

    id = db.Column(db.Integer, primary_key=True)
    code_hash = db.Column(db.String(255), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    account = db.relationship("Account", foreign_keys=[account_id])
