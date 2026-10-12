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
from sqlalchemy.engine import make_url  # noqa: E402

from app import clock  # noqa: E402
from app.auth.passwords import hash_password
from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Role, User  # noqa: E402
from app.db.session import _sessionmaker, get_db, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402


def _assert_test_database(url: str) -> None:
    """Abort the run unless the DB name contains 'test' (the suite runs drop_all on it)."""
    database = make_url(url).database or ""
    if "test" not in database:
        pytest.exit(
            "TEST_DATABASE_URL phải trỏ tới DB có tên chứa 'test' "
            f"(hiện là '{database}'). Bộ test sẽ xóa toàn bộ bảng.",
            returncode=2,
        )


@pytest.fixture
def engine() -> Iterator[Engine]:
    """In-memory SQLite by default; real Postgres when TEST_DATABASE_URL is set."""
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        _assert_test_database(test_url)
    eng = make_engine(test_url or "sqlite://")
    if test_url:
        Base.metadata.drop_all(eng)  # clean slate in case a previous run crashed
    Base.metadata.create_all(eng)
    yield eng
    if test_url:
        Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db_url_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """Point DATABASE_URL at a temp-file SQLite DB so CLIs open their own session.

    Always SQLite, even when TEST_DATABASE_URL is set (CLI/migration tests are SQLite-only).
    """
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


@pytest.fixture
def client_factory(client: TestClient) -> Callable[[], TestClient]:
    """Factory: a fresh, cookie-isolated TestClient on the same app (and DB session)."""

    def _make() -> TestClient:
        return TestClient(client.app, base_url="https://testserver")

    return _make


@pytest.fixture
def logged_in(
    client_factory: Callable[[], TestClient], make_user: Callable[..., User]
) -> Callable[[Role], TestClient]:
    """Factory: new TestClient logged in (via POST /login) as a fresh user of the given role."""
    counter = iter(range(1_000_000))

    def _login(role: Role) -> TestClient:
        username = f"{role.value}_{next(counter)}"
        make_user(username=username, password="Matkhau#2026", role=role)
        c = client_factory()
        r = c.post(
            "/login",
            data={"username": username, "password": "Matkhau#2026", "csrf_token": csrf_of(c)},
            follow_redirects=False,
        )
        assert r.status_code == 303
        return c

    return _login
