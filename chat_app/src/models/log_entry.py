from datetime import datetime, timezone

from src.models.base import db


class LogEntry(db.Model):
    __tablename__ = "log_entries"
    __table_args__ = (
        db.Index("ix_log_entries_kind_account_created", "kind", "account_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)
    source = db.Column(db.String(100), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    account = db.relationship("Account", foreign_keys=[account_id])
