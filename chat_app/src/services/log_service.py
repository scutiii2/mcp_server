from src.models import Account, LogEntry


def log_action(db_session, account: Account, source: str, message: str, details: str | None = None) -> LogEntry:
    entry = LogEntry(
        kind="action",
        account_id=account.id,
        source=source,
        message=message,
        details=details,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


def log_chat_trace(db_session, account: Account, source: str, message: str, details: str | None = None) -> LogEntry:
    entry = LogEntry(
        kind="chat_trace",
        account_id=account.id,
        source=source,
        message=message,
        details=details,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


def log_error(
    db_session, account: Account | None, source: str, message: str, details: str | None = None
) -> LogEntry:
    entry = LogEntry(
        kind="error",
        account_id=account.id if account else None,
        source=source,
        message=message,
        details=details,
    )
    db_session.add(entry)
    db_session.commit()
    return entry


def list_entries(db_session, kind: str, account_id: int | None = None, limit: int = 200) -> list[LogEntry]:
    query = db_session.query(LogEntry).filter_by(kind=kind)
    if account_id is None:
        query = query.filter(LogEntry.account_id.is_(None))
    else:
        query = query.filter(LogEntry.account_id == account_id)
    return query.order_by(LogEntry.created_at.desc()).limit(limit).all()
