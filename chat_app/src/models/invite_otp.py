from datetime import datetime, timezone

from src.models.base import db


class InviteOTP(db.Model):
    __tablename__ = "invite_otps"

    id = db.Column(db.Integer, primary_key=True)
    code_hash = db.Column(db.String(255), nullable=False)
    created_by_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    invitee_email = db.Column(db.String(255), nullable=True)
    delivery_method = db.Column(db.String(20), nullable=False)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship("Account", foreign_keys=[created_by_account_id])
