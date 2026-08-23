import hashlib
from datetime import datetime, timezone

from src.models import DeviceFingerprint


def _subnet_24(ip_address: str) -> str:
    parts = ip_address.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0/24"
    return ip_address


def compute_fingerprint(config: dict, user_agent: str, accept_language: str, ip_address: str) -> str:
    signals = config.get("signals", ["user_agent", "accept_language", "ip_subnet"])
    values = {
        "user_agent": user_agent or "",
        "accept_language": accept_language or "",
        "ip_subnet": _subnet_24(ip_address or ""),
    }
    raw = "|".join(values.get(signal, "") for signal in signals)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_new_device(db_session, account_id: int, fingerprint_hash: str) -> bool:
    existing = (
        db_session.query(DeviceFingerprint)
        .filter_by(account_id=account_id, fingerprint_hash=fingerprint_hash)
        .first()
    )
    return existing is None


def record_device(db_session, account_id: int, fingerprint_hash: str) -> DeviceFingerprint:
    now = datetime.now(timezone.utc)
    existing = (
        db_session.query(DeviceFingerprint)
        .filter_by(account_id=account_id, fingerprint_hash=fingerprint_hash)
        .first()
    )
    if existing:
        existing.last_seen_at = now
        db_session.commit()
        return existing

    device = DeviceFingerprint(
        account_id=account_id,
        fingerprint_hash=fingerprint_hash,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(device)
    db_session.commit()
    return device
