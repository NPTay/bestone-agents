from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi import APIRouter, Depends, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import orm

from app.auth.dependencies import require_login, require_role
from app.auth.session import (
    clear_session_cookie,
    create_session,
    destroy_session,
    destroy_user_sessions,
    resolve_session,
    set_session_cookie,
)
from app.config import get_settings
from app.db.models import Role, User, UserSession
from tests.conftest import FrozenNow

MakeUser = Callable[..., User]


def test_session_expires_after_8h_idle(
    db: orm.Session, make_user: MakeUser, frozen_now: FrozenNow
) -> None:
    u = make_user()
    tok = create_session(db, u, remember=False, ip=None, user_agent=None)
    frozen_now.advance(timedelta(hours=7, minutes=59))
    assert resolve_session(db, tok) == u
    frozen_now.advance(timedelta(hours=7, minutes=59))
    assert resolve_session(db, tok) == u  # sliding
    frozen_now.advance(timedelta(hours=8, minutes=1))
    assert resolve_session(db, tok) is None


def test_remember_lasts_30_days(
    db: orm.Session, make_user: MakeUser, frozen_now: FrozenNow
) -> None:
    u = make_user()
    tok = create_session(db, u, remember=True, ip=None, user_agent=None)
    frozen_now.advance(timedelta(days=29))
    assert resolve_session(db, tok) == u
    frozen_now.advance(timedelta(days=2))
    assert resolve_session(db, tok) is None


def test_inactive_user_rejected_immediately(db: orm.Session, make_user: MakeUser) -> None:
    u = make_user()
    tok = create_session(db, u, remember=False, ip=None, user_agent=None)
    u.is_active = False
    db.commit()
    assert resolve_session(db, tok) is None


def test_token_stored_hashed(db: orm.Session, make_user: MakeUser) -> None:
    tok = create_session(db, make_user(), remember=False, ip=None, user_agent=None)
    assert db.query(UserSession).one().token_hash != tok


def test_missing_or_unknown_token(db: orm.Session) -> None:
    assert resolve_session(db, None) is None
    assert resolve_session(db, "nope") is None


def test_destroy_session(db: orm.Session, make_user: MakeUser) -> None:
    tok = create_session(db, make_user(), remember=False, ip=None, user_agent=None)
    destroy_session(db, tok)
    assert resolve_session(db, tok) is None


def test_destroy_user_sessions_except(db: orm.Session, make_user: MakeUser) -> None:
    u = make_user()
    keep = create_session(db, u, remember=False, ip=None, user_agent=None)
    drop = create_session(db, u, remember=True, ip=None, user_agent=None)
    destroy_user_sessions(db, u.id, except_token=keep)
    assert resolve_session(db, keep) == u
    assert resolve_session(db, drop) is None
    destroy_user_sessions(db, u.id)
    assert resolve_session(db, keep) is None


def test_cookie_flags_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    try:
        resp = Response()
        set_session_cookie(resp, "t", remember=False)
        c = resp.headers["set-cookie"].lower()
        assert "httponly" in c and "secure" in c and "samesite=lax" in c and "max-age" not in c
        assert "expires" not in c
    finally:
        get_settings.cache_clear()


def test_cookie_remember_has_max_age(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    get_settings.cache_clear()
    try:
        resp = Response()
        set_session_cookie(resp, "t", remember=True)
        assert f"max-age={30 * 86400}" in resp.headers["set-cookie"].lower()
    finally:
        get_settings.cache_clear()


def test_cookie_dev_omits_secure() -> None:
    get_settings.cache_clear()
    resp = Response()
    set_session_cookie(resp, "t", remember=False)
    c = resp.headers["set-cookie"].lower()
    assert "secure" not in c and "httponly" in c


def test_clear_cookie() -> None:
    resp = Response()
    clear_session_cookie(resp)
    assert "bestone_session=" in resp.headers["set-cookie"]


def _mount(client: TestClient) -> None:
    router = APIRouter()

    @router.get("/_me")
    def me(request: Request, user: User = Depends(require_login)) -> dict[str, str]:  # noqa: B008
        assert request.state.user is user
        return {"u": user.username}

    @router.get("/_gd")
    def gd(user: User = Depends(require_role(Role.giam_doc))) -> dict[str, str]:  # noqa: B008
        return {"u": user.username}

    client.app.include_router(router)  # type: ignore[attr-defined]


def test_require_login_redirects_without_session(client: TestClient) -> None:
    _mount(client)
    r = client.get("/_me", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_require_login_and_role(db: orm.Session, client: TestClient, make_user: MakeUser) -> None:
    _mount(client)
    gd = make_user("gd")
    kt = make_user("kt", role=Role.ke_toan)
    client.cookies.set("bestone_session", create_session(db, gd, False, None, None))
    assert client.get("/_me").json() == {"u": "gd"}
    assert client.get("/_gd").status_code == 200
    client.cookies.clear()
    client.cookies.set("bestone_session", create_session(db, kt, False, None, None))
    assert client.get("/_me").status_code == 200
    assert client.get("/_gd").status_code == 403


def test_deactivated_user_loses_live_session(
    db: orm.Session, client: TestClient, make_user: MakeUser
) -> None:
    _mount(client)
    u = make_user()
    client.cookies.set("bestone_session", create_session(db, u, False, None, None))
    assert client.get("/_me").status_code == 200
    u.is_active = False
    db.commit()
    r = client.get("/_me", follow_redirects=False)
    assert r.status_code == 303
