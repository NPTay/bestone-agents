import logging
import re
from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import orm, select

from app.config import get_settings
from app.db.models import Alert, AuditLog, Role, User, UserSession
from tests.conftest import FrozenNow, csrf_of, strip_csrf

GENERIC = "Sai tên đăng nhập hoặc mật khẩu"
MakeUser = Callable[..., User]


def login(client: TestClient, u: str, p: str, remember: bool = False) -> Response:
    token = csrf_of(client)
    return client.post(
        "/login",
        data={
            "username": u,
            "password": p,
            "csrf_token": token,
            **({"remember_me": "on"} if remember else {}),
        },
        follow_redirects=False,
    )


def test_login_page_per_spec(client: TestClient) -> None:
    html = client.get("/login").text
    assert '<html lang="vi"' in html
    for text in [
        "C.G. Engineering — Bestone Console",
        "Tên đăng nhập",
        "Mật khẩu",
        "Ghi nhớ đăng nhập",
        "Đăng nhập",
        "Quên mật khẩu? Liên hệ Giám đốc",
    ]:
        assert text in html
    assert "viewport" in html
    assert "Google" not in html and "Facebook" not in html


def test_giam_doc_redirects_to_dashboard(client: TestClient, make_user: MakeUser) -> None:
    make_user(username="gd", role=Role.giam_doc)
    r = login(client, "gd", "Matkhau#2026")
    assert r.status_code == 303 and r.headers["location"] == "/dashboard"


def test_ke_toan_redirects_to_reports(client: TestClient, make_user: MakeUser) -> None:
    make_user(username="kt", role=Role.ke_toan)
    assert login(client, "kt", "Matkhau#2026").headers["location"] == "/reports"


def test_login_sets_session_cookie_and_rotates_csrf(
    client: TestClient, make_user: MakeUser, db: orm.Session
) -> None:
    make_user(username="gd")
    csrf_of(client)
    before = client.cookies.get("bestone_csrf")
    r = login(client, "gd", "Matkhau#2026")
    cookies = r.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("bestone_session="))
    assert "HttpOnly" in session_cookie and "Max-Age" not in session_cookie
    assert any(c.startswith("bestone_csrf=") for c in cookies)
    assert client.cookies.get("bestone_csrf") != before
    assert db.scalar(select(UserSession)) is not None
    assert db.query(AuditLog).filter_by(action="login_success").count() == 1


def test_remember_me_sets_max_age(client: TestClient, make_user: MakeUser) -> None:
    make_user(username="gd")
    r = login(client, "gd", "Matkhau#2026", remember=True)
    cookie = next(c for c in r.headers.get_list("set-cookie") if c.startswith("bestone_session="))
    assert "Max-Age=2592000" in cookie


def test_login_page_redirects_when_logged_in(client: TestClient, make_user: MakeUser) -> None:
    make_user(username="kt", role=Role.ke_toan)
    login(client, "kt", "Matkhau#2026")
    r = client.get("/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/reports"


def test_unknown_user_and_wrong_password_same_response(
    client: TestClient, make_user: MakeUser
) -> None:
    make_user(username="gd")
    a = login(client, "khongco", "x")
    b = login(client, "gd", "x")
    assert a.status_code == b.status_code == 200
    assert GENERIC in a.text and GENERIC in b.text
    assert strip_csrf(a.text) == strip_csrf(b.text)


def test_unknown_user_runs_dummy_verify(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.auth.service as service

    calls: list[int] = []
    monkeypatch.setattr(service, "dummy_verify", lambda: calls.append(1))
    login(client, "khongco", "x")
    assert calls == [1]


def test_lock_after_5_failures(
    client: TestClient,
    make_user: MakeUser,
    frozen_now: FrozenNow,
    respx_mock,  # type: ignore[no-untyped-def]
    db: orm.Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    get_settings.cache_clear()
    tg = respx_mock.post(url__regex=r"https://api\.telegram\.org/.*").respond(
        200, json={"ok": True}
    )
    make_user(username="gd")
    for _ in range(5):
        login(client, "gd", "x")
    r = login(client, "gd", "Matkhau#2026")
    # 01:00 UTC + 15 min = 08:15 Asia/Ho_Chi_Minh
    assert "Tài khoản tạm khóa, thử lại sau 08:15" in r.text
    assert tg.called
    sent = tg.calls.last.request.content.decode()
    assert "gd" in sent and "Matkhau#2026" not in sent
    assert db.query(AuditLog).filter_by(action="account_locked").count() == 1
    assert db.query(Alert).filter_by(level="warn").count() == 1
    db.expire_all()
    user = db.scalar(select(User))
    assert user is not None and user.failed_attempts == 5  # locked login did not increment
    frozen_now.advance(timedelta(minutes=15, seconds=1))
    assert login(client, "gd", "Matkhau#2026").status_code == 303


def test_failure_window_restarts(
    client: TestClient, make_user: MakeUser, frozen_now: FrozenNow
) -> None:
    make_user(username="gd")
    for _ in range(4):
        login(client, "gd", "x")
    frozen_now.advance(timedelta(minutes=16))
    login(client, "gd", "x")
    assert login(client, "gd", "Matkhau#2026").status_code == 303


def test_success_resets_counter(client: TestClient, make_user: MakeUser, db: orm.Session) -> None:
    make_user(username="gd")
    for _ in range(3):
        login(client, "gd", "x")
    login(client, "gd", "Matkhau#2026")
    db.expire_all()
    user = db.scalar(select(User))
    assert user is not None and user.failed_attempts == 0 and user.last_login_at is not None


def test_inactive_user_cannot_login(
    client: TestClient, make_user: MakeUser, db: orm.Session
) -> None:
    make_user(username="gd", is_active=False)
    r = login(client, "gd", "Matkhau#2026")
    assert GENERIC in r.text
    db.expire_all()
    user = db.scalar(select(User))
    assert user is not None and user.failed_attempts == 0
    assert db.scalar(select(UserSession)) is None


def test_login_without_csrf_rejected(client: TestClient, make_user: MakeUser) -> None:
    make_user(username="gd")
    r = client.post("/login", data={"username": "gd", "password": "Matkhau#2026"})
    assert r.status_code == 403


def test_rate_limit_per_ip(client: TestClient) -> None:
    codes = [login(client, "x", "x").status_code for _ in range(11)]
    assert codes[-1] == 429
    assert "Quá nhiều lần thử" in login(client, "x", "x").text


def test_rate_limit_keys_on_forwarded_client(
    proxied_client: Callable[[str], TestClient],
) -> None:
    for _ in range(10):
        login(proxied_client("1.1.1.1"), "x", "x")
    assert login(proxied_client("1.1.1.1"), "x", "x").status_code == 429
    assert login(proxied_client("2.2.2.2"), "x", "x").status_code == 200


def test_logout_clears_session(client: TestClient, make_user: MakeUser, db: orm.Session) -> None:
    make_user(username="gd")
    login(client, "gd", "Matkhau#2026")
    assert db.scalar(select(UserSession)) is not None
    csrf_before = client.cookies.get("bestone_csrf")
    r = client.post("/logout", data={"csrf_token": csrf_of(client)}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    db.expire_all()
    assert db.scalar(select(UserSession)) is None
    cookies = r.headers.get_list("set-cookie")
    cleared = next(c for c in cookies if c.startswith("bestone_session="))
    assert re.search(r"Max-Age=0", cleared)
    assert client.cookies.get("bestone_csrf") != csrf_before
    assert db.query(AuditLog).filter_by(action="logout").count() == 1


def test_logout_requires_csrf(client: TestClient, make_user: MakeUser) -> None:
    make_user(username="gd")
    login(client, "gd", "Matkhau#2026")
    assert client.post("/logout", data={}).status_code == 403


def test_password_never_logged(
    client: TestClient, make_user: MakeUser, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    make_user(username="gd")
    login(client, "gd", "BiMat-XYZ-123")
    login(client, "gd", "Matkhau#2026")
    assert "BiMat-XYZ-123" not in caplog.text


def test_locked_login_runs_dummy_verify_not_password_check(
    client: TestClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.auth.service as service

    make_user(username="gd")
    for _ in range(5):
        login(client, "gd", "x")
    dummy: list[int] = []
    real: list[int] = []
    monkeypatch.setattr(service, "dummy_verify", lambda: dummy.append(1))
    monkeypatch.setattr(service, "verify_password", lambda h, p: real.append(1) or True)
    r = login(client, "gd", "Matkhau#2026")
    assert "Tài khoản tạm khóa" in r.text
    assert dummy == [1] and real == []


def test_failure_at_exact_window_edge_restarts(
    client: TestClient, make_user: MakeUser, frozen_now: FrozenNow, db: orm.Session
) -> None:
    make_user(username="gd")
    for _ in range(4):
        login(client, "gd", "x")
    frozen_now.advance(timedelta(minutes=15))
    login(client, "gd", "x")
    db.expire_all()
    user = db.scalar(select(User))
    assert user is not None and user.failed_attempts == 1 and user.locked_until is None
