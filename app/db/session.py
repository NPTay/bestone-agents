from collections.abc import Iterator
from functools import lru_cache
from typing import Any

from sqlalchemy import Engine, StaticPool, create_engine, event, orm

from app.config import get_settings


def _sqlite_wal(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def make_engine(url: str) -> Engine:
    """Create an engine; SQLite gets thread-safe settings (in-memory shares one connection)."""
    if url.startswith("sqlite"):
        if url in ("sqlite://", "sqlite:///:memory:"):
            return create_engine(
                url, connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
        # File DB shared by the tick and Telegram threads: wait for locks, use WAL.
        engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
        event.listen(engine, "connect", _sqlite_wal)
        return engine
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def _sessionmaker() -> orm.sessionmaker[orm.Session]:
    engine = make_engine(get_settings().DATABASE_URL)
    return orm.sessionmaker(bind=engine, expire_on_commit=False)


def open_session() -> orm.Session:
    """Open a standalone session (for CLIs/jobs outside FastAPI); use as a context manager."""
    return _sessionmaker()()


def get_db() -> Iterator[orm.Session]:
    """FastAPI dependency yielding a DB session (built lazily from settings)."""
    session = _sessionmaker()()
    try:
        yield session
    finally:
        session.close()
