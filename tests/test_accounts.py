from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import orm, select

from app import clock
from app.auth.passwords import verify_password
from app.db.models import AuditLog, Role, User, UserSession
from tests.conftest import csrf_of
from tests.test_login import login

LoggedIn = Callable[[Role], TestClient]
MakeUser = Callable[..., User]
Factory = Callable[[], TestClient]
NEW_PW = "MatkhauMoi#2027"


def _create(c: TestClient, **over: str) -> Response:
    data = {
        "username": "ketoan",
        "full_name": "Kế toán",
        "password": "Matkhau#2026",
        "role": "ke_toan",
        "csrf_token": csrf_of(c),
    }
    data.update(over)
    return c.post("/dashboard/users", data=data, follow_redirects=False)


def _change(c: TestClient, current: str, new: str, confirm: str) -> Response:
    return c.post(
        "/account/change-password",
        data={
            "current_password": current,
            "new_password": new,
            "confirm_password": confirm,
            "csrf_token": csrf_of(c),
        },
    )


def test_giam_doc_creates_ke_toan(logged_in: LoggedIn, db: orm.Session) -> None:
    c = logged_in(Role.giam_doc)
    r = _create(c)
    assert r.status_code == 303 and r.headers["location"] == "/dashboard/users"
    created = db.query(User).filter_by(username="ketoan", role=Role.ke_toan).one()
    assert verify_password(created.password_hash, "Matkhau#2026")
    audit = db.query(AuditLog).filter_by(action="user_created").one()
    assert audit.entity_id == str(created.id)
    assert audit.actor == db.query(User).filter_by(role=Role.giam_doc).one().id
    assert "Matkhau" not in str(audit.detail)


def test_created_user_can_login(logged_in: LoggedIn, client_factory: Factory) -> None:
    _create(logged_in(Role.giam_doc))
    r = login(client_factory(), "ketoan", "Matkhau#2026")
    assert r.status_code == 303 and r.headers["location"] == "/reports"


def test_duplicate_username_shows_error(logged_in: LoggedIn, db: orm.Session) -> None:
    c = logged_in(Role.giam_doc)
    _create(c)
    r = _create(c)
    assert r.status_code == 400
    assert "Tên đăng nhập đã tồn tại" in r.text
    assert db.query(User).filter_by(username="ketoan").count() == 1


@pytest.mark.parametrize("over", [{"password": "ngan"}, {"role": "admin"}, {"username": "  "}])
def test_create_validation(logged_in: LoggedIn, db: orm.Session, over: dict[str, str]) -> None:
    r = _create(logged_in(Role.giam_doc), **over)
    assert r.status_code == 400
    assert db.query(User).filter_by(username="ketoan").count() == 0


def test_ke_toan_cannot_create(logged_in: LoggedIn, db: orm.Session) -> None:
    r = _create(logged_in(Role.ke_toan))
    assert r.status_code == 403
    assert db.query(User).filter_by(username="ketoan").count() == 0


def test_create_requires_csrf(logged_in: LoggedIn) -> None:
    c = logged_in(Role.giam_doc)
    r = c.post(
        "/dashboard/users", data={"username": "x", "password": "Matkhau#2026", "role": "ke_toan"}
    )
    assert r.status_code == 403


def test_cannot_deactivate_self(logged_in: LoggedIn, db: orm.Session) -> None:
    c = logged_in(Role.giam_doc)
    me = db.query(User).one()
    r = c.post(f"/dashboard/users/{me.id}/toggle-active", data={"csrf_token": csrf_of(c)})
    assert r.status_code == 400
    db.refresh(me)
    assert me.is_active is True
    assert c.get("/dashboard").status_code == 200


def test_toggle_active_kills_sessions_and_audits(logged_in: LoggedIn, db: orm.Session) -> None:
    gd = logged_in(Role.giam_doc)
    kt = logged_in(Role.ke_toan)
    target = db.query(User).filter_by(role=Role.ke_toan).one()
    assert kt.get("/reports").status_code == 200
    r = gd.post(
        f"/dashboard/users/{target.id}/toggle-active",
        data={"csrf_token": csrf_of(gd)},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/dashboard/users"
    db.refresh(target)
    assert target.is_active is False
    assert db.scalar(select(UserSession).where(UserSession.user_id == target.id)) is None
    assert kt.get("/reports", follow_redirects=False).status_code == 303
    assert db.query(AuditLog).filter_by(action="user_deactivated").count() == 1
    gd.post(f"/dashboard/users/{target.id}/toggle-active", data={"csrf_token": csrf_of(gd)})
    db.refresh(target)
    assert target.is_active is True
    assert db.query(AuditLog).filter_by(action="user_activated").count() == 1


def test_toggle_unknown_user_404(logged_in: LoggedIn) -> None:
    c = logged_in(Role.giam_doc)
    r = c.post(
        "/dashboard/users/00000000-0000-0000-0000-000000000000/toggle-active",
        data={"csrf_token": csrf_of(c)},
    )
    assert r.status_code == 404


def test_reset_password_unlocks_and_kills_sessions(
    logged_in: LoggedIn, client_factory: Factory, db: orm.Session
) -> None:
    gd = logged_in(Role.giam_doc)
    kt = logged_in(Role.ke_toan)
    target = db.query(User).filter_by(role=Role.ke_toan).one()
    target.failed_attempts = 5
    target.last_failed_at = clock.utcnow()
    target.locked_until = clock.utcnow()
    db.commit()
    r = gd.post(
        f"/dashboard/users/{target.id}/reset-password",
        data={"new_password": NEW_PW, "csrf_token": csrf_of(gd)},
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == "/dashboard/users"
    db.refresh(target)
    assert verify_password(target.password_hash, NEW_PW)
    assert target.failed_attempts == 0 and target.locked_until is None
    assert target.last_failed_at is None
    assert kt.get("/reports", follow_redirects=False).status_code == 303
    audit = db.query(AuditLog).filter_by(action="user_password_reset").one()
    assert NEW_PW not in str(audit.detail)
    assert login(client_factory(), target.username, NEW_PW).status_code == 303


def test_reset_password_validation(logged_in: LoggedIn, db: orm.Session) -> None:
    gd = logged_in(Role.giam_doc)
    logged_in(Role.ke_toan)
    target = db.query(User).filter_by(role=Role.ke_toan).one()
    old = target.password_hash
    r = gd.post(
        f"/dashboard/users/{target.id}/reset-password",
        data={"new_password": "ngan", "csrf_token": csrf_of(gd)},
    )
    assert r.status_code == 400 and "ít nhất" in r.text
    db.refresh(target)
    assert target.password_hash == old


def test_change_password_success(logged_in: LoggedIn, db: orm.Session) -> None:
    c = logged_in(Role.ke_toan)
    r = _change(c, "Matkhau#2026", NEW_PW, NEW_PW)
    assert r.status_code == 200 and "Đã đổi mật khẩu" in r.text
    user = db.query(User).one()
    assert verify_password(user.password_hash, NEW_PW)
    audit = db.query(AuditLog).filter_by(action="password_changed").one()
    assert NEW_PW not in str(audit.detail)
    assert c.get("/reports").status_code == 200


@pytest.mark.parametrize(
    ("current", "new", "confirm", "msg"),
    [
        ("sai-mat-khau", NEW_PW, NEW_PW, "Mật khẩu hiện tại không đúng"),
        ("Matkhau#2026", NEW_PW, NEW_PW + "x", "không khớp"),
        ("Matkhau#2026", "ngan", "ngan", "ít nhất"),
    ],
)
def test_change_password_errors(
    logged_in: LoggedIn, db: orm.Session, current: str, new: str, confirm: str, msg: str
) -> None:
    c = logged_in(Role.giam_doc)
    old = db.query(User).one().password_hash
    r = _change(c, current, new, confirm)
    assert r.status_code == 400 and msg in r.text
    db.expire_all()
    assert db.query(User).one().password_hash == old


def test_change_password_requires_csrf_and_login(logged_in: LoggedIn, client: TestClient) -> None:
    c = logged_in(Role.giam_doc)
    assert c.post("/account/change-password", data={"current_password": "x"}).status_code == 403
    r = client.get("/account/change-password", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_change_password_kills_other_sessions(client_factory: Factory, make_user: MakeUser) -> None:
    make_user(username="gd", role=Role.giam_doc)
    a, b = client_factory(), client_factory()
    assert login(a, "gd", "Matkhau#2026").status_code == 303
    assert login(b, "gd", "Matkhau#2026").status_code == 303
    assert b.get("/reports").status_code == 200
    assert _change(a, "Matkhau#2026", NEW_PW, NEW_PW).status_code == 200
    r = b.get("/reports", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert a.get("/reports").status_code == 200


def test_malformed_uuid_renders_html_422(logged_in: LoggedIn) -> None:
    c = logged_in(Role.giam_doc)
    r = c.post("/dashboard/users/not-a-uuid/toggle-active", data={"csrf_token": csrf_of(c)})
    assert r.status_code == 422
    assert "text/html" in r.headers["content-type"]
    assert "Dữ liệu không hợp lệ" in r.text
