from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, StaticPool, create_engine, orm

from app.config import get_settings


def make_engine(url: str) -> Engine:
    """Create an engine; SQLite gets thread-safe settings (in-memory shares one connection)."""
    if url.startswith("sqlite"):
        if url in ("sqlite://", "sqlite:///:memory:"):
            return create_engine(
                url, connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def _sessionmaker() -> orm.sessionmaker[orm.Session]:
    engine = make_engine(get_settings().DATABASE_URL)
    return orm.sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[orm.Session]:
    """FastAPI dependency yielding a DB session (built lazily from settings)."""
    session = _sessionmaker()()
    try:
        yield session
    finally:
        session.close()
