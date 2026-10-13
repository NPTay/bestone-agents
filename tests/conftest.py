from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, orm

from app import clock
from app.config import Settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.session import make_engine


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep OS environment variables (real keys, model names) out of every test's Settings."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[orm.Session]:
    session = orm.sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def db_factory(engine: Engine) -> Callable[[], orm.Session]:
    """Factory of sessions bound to the same test engine as `db`."""
    return orm.sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def frozen_clock(monkeypatch: pytest.MonkeyPatch) -> Callable[[datetime], None]:
    """Return a setter that pins app.clock.utcnow to a given datetime."""

    def _set(value: datetime) -> None:
        pinned = value if value.tzinfo else value.replace(tzinfo=UTC)
        monkeypatch.setattr(clock, "utcnow", lambda: pinned)

    return _set
