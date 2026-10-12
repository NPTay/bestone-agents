from datetime import timedelta

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Engine, orm, select

from app import clock
from app.auth.ratelimit import RateLimiter
from app.auth.service import register_failure
from app.db.models import Role, User
from tests.conftest import FrozenNow


def test_failures_from_stale_sessions_both_count(db_url_env: Engine) -> None:
    maker = orm.sessionmaker(bind=db_url_env, expire_on_commit=False)
    with maker() as seed:
        user = User(username="gd", password_hash="x", role=Role.giam_doc)
        seed.add(user)
        seed.commit()
        uid = user.id
    with maker() as a, maker() as b:
        ua = a.get(User, uid)
        ub = b.get(User, uid)  # both hold failed_attempts == 0
        assert ua is not None and ub is not None
        now = clock.utcnow()
        register_failure(a, ua, now)
        register_failure(b, ub, now)
    with maker() as check:
        fresh = check.scalar(select(User).where(User.id == uid))
        assert fresh is not None and fresh.failed_attempts == 2


def test_rate_limiter_drops_stale_keys(frozen_now: FrozenNow) -> None:
    limiter = RateLimiter(max_hits=10, window_s=60)
    for i in range(50):
        assert limiter.hit(f"10.0.0.{i}")
    assert limiter.key_count() == 50
    frozen_now.advance(timedelta(seconds=61))
    assert limiter.hit("9.9.9.9")
    assert limiter.key_count() == 1


def test_admin_api_errors_are_json(client: TestClient) -> None:
    def boom() -> None:
        raise HTTPException(status_code=403, detail="Không có quyền")

    client.app.add_api_route("/admin_api/boom", boom)  # type: ignore[attr-defined]
    r = client.get("/admin_api/boom")
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"detail": "Không có quyền"}


def test_http_error_headers_pass_through(client: TestClient) -> None:
    r = client.post("/health")
    assert r.status_code == 405
    assert "GET" in r.headers["allow"]
