from datetime import datetime, timezone

from src.models.base import db


class SecurityEvent(db.Model):
    __tablename__ = "security_events"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
    event_type = db.Column(db.String(50), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    details = db.Column(db.String(500), nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    account = db.relationship("Account", foreign_keys=[account_id])
