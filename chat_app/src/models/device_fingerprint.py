from datetime import datetime, timezone

from src.models.base import db


class DeviceFingerprint(db.Model):
    __tablename__ = "device_fingerprints"

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    fingerprint_hash = db.Column(db.String(128), nullable=False)
    first_seen_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    account = db.relationship("Account", foreign_keys=[account_id])
