import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SESSION_SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "dev")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, orm  # noqa: E402

from app import clock  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Role, User  # noqa: E402
from app.db.session import get_db, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402


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
def client(db: orm.Session) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    # https base URL so Secure cookies round-trip in later tasks
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    get_settings.cache_clear()


@pytest.fixture
def make_user(db: orm.Session) -> Callable[..., User]:
    def _make(
        username: str = "gd",
        password: str = "Matkhau#2026",
        role: Role = Role.giam_doc,
        is_active: bool = True,
    ) -> User:
        # TODO(Task 4): switch to hash_password(password) once password hashing exists.
        user = User(
            username=username,
            password_hash="unhashed:" + password,
            role=role,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        return user

    return _make


class FrozenNow:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> FrozenNow:
    holder = FrozenNow(datetime(2026, 10, 12, 1, 0, tzinfo=UTC))
    monkeypatch.setattr(clock, "utcnow", lambda: holder.now)
    return holder
