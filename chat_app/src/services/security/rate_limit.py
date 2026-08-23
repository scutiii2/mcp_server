from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_

from src.models import LoginAttempt


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_seconds: int | None = None
    reason: str | None = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _recent_failed_attempts(db_session, since, ip_address=None, account_id=None):
    query = db_session.query(LoginAttempt).filter(
        LoginAttempt.success.is_(False),
        LoginAttempt.created_at >= since,
    )
    filters = []
    if ip_address is not None:
        filters.append(LoginAttempt.ip_address == ip_address)
    if account_id is not None:
        filters.append(LoginAttempt.account_id == account_id)
    if filters:
        query = query.filter(or_(*filters))
    return query.order_by(LoginAttempt.created_at.desc()).all()


def check_rate_limit(
    config: dict, db_session, ip_address: str, account_id: int | None = None
) -> RateLimitResult:
    if not config.get("enabled", False):
        return RateLimitResult(allowed=True)

    scope = config.get("scope", "both")
    scoped_ip = ip_address if scope in ("ip", "both") else None
    scoped_account = account_id if scope in ("account", "both") else None

    if scoped_ip is None and scoped_account is None:
        return RateLimitResult(allowed=True)

    max_attempts = config["max_attempts"]
    window_seconds = config["window_seconds"]
    lockout_seconds = config["lockout_seconds"]

    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=window_seconds)

    attempts = _recent_failed_attempts(
        db_session, since, ip_address=scoped_ip, account_id=scoped_account
    )

    if len(attempts) < max_attempts:
        return RateLimitResult(allowed=True)

    most_recent = _as_utc(attempts[0].created_at)
    lockout_ends_at = most_recent + timedelta(seconds=lockout_seconds)

    if now >= lockout_ends_at:
        return RateLimitResult(allowed=True)

    retry_after = int((lockout_ends_at - now).total_seconds())
    return RateLimitResult(allowed=False, retry_after_seconds=retry_after, reason="rate_limited")
