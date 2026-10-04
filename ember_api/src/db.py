"""Async SQLAlchemy engine/session factory and the declarative base."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC: SQLite drops tzinfo on read, so every stored time is
    naive UTC and compared as such."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Database:
    """Owns one engine and hands out sessions; created per app (and per test)."""

    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url)
        # SQLite ignores foreign keys (and so ON DELETE CASCADE) unless asked.
        event.listen(self.engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_tables(self) -> None:
        # Importing registers every model on Base.metadata.
        from src import models  # noqa: F401

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
