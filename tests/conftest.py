import os
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SESSION_SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "dev")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, orm  # noqa: E402

from app import clock  # noqa: E402
from app.auth.passwords import hash_password
from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Role, User  # noqa: E402
from app.db.session import _sessionmaker, get_db, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = make_engine("sqlite://")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_url_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """Point DATABASE_URL at a temp-file SQLite DB so CLIs open their own session."""
    eng = make_engine(f"sqlite:///{tmp_path / 'cli.db'}")
    Base.metadata.create_all(eng)
    monkeypatch.setenv("DATABASE_URL", str(eng.url))
    get_settings.cache_clear()
    _sessionmaker.cache_clear()
    yield eng
    get_settings.cache_clear()
    _sessionmaker.cache_clear()
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
        user = User(
            username=username,
            password_hash=hash_password(password),
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


@pytest.fixture(autouse=True)
def _reset_login_limiter() -> None:
    from app.auth.ratelimit import login_limiter

    login_limiter.reset()


_CSRF_INPUT = re.compile(r'(<input[^>]*name="csrf_token"[^>]*value=")[^"]*(")')


def csrf_of(client: TestClient) -> str:
    """Return the form CSRF token for the client's current CSRF cookie."""
    from app.auth.csrf import CSRF_COOKIE, form_token_for

    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get("/login").text)
    if match:
        return match.group(1)
    # Already logged in: /login redirects, so derive the token from the cookie.
    cookie = client.cookies.get(CSRF_COOKIE)
    assert cookie, "no CSRF cookie available"
    return form_token_for(cookie)


def strip_csrf(html: str) -> str:
    """Blank the CSRF hidden-input value so two renders can be compared."""
    return _CSRF_INPUT.sub(r"\1\2", html)


@pytest.fixture
def proxied_client(db: orm.Session) -> Callable[[str], TestClient]:
    """Factory: client whose requests carry X-Forwarded-For, via a trusted proxy."""
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

    def _make(xff: str) -> TestClient:
        get_settings.cache_clear()
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        wrapped = ProxyHeadersMiddleware(app, trusted_hosts=["testclient"])
        return TestClient(wrapped, base_url="https://testserver", headers={"X-Forwarded-For": xff})

    return _make
