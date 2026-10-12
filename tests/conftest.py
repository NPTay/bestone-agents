import os
from collections.abc import Iterator

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SESSION_SECRET_KEY", "test-secret")
os.environ.setdefault("APP_ENV", "dev")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import orm  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db.session import get_db, make_engine  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def db_session() -> Iterator[orm.Session]:
    engine = make_engine("sqlite://")
    session = orm.sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session: orm.Session) -> Iterator[TestClient]:
    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    # https base URL so Secure cookies round-trip in later tasks
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    get_settings.cache_clear()
