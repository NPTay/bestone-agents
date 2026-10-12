from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import orm

from app.db.models import Role, Setting
from tests.conftest import csrf_of

LoggedIn = Callable[[Role], TestClient]


@pytest.mark.parametrize("path", ["/dashboard", "/dashboard/users", "/admin_api/ping"])
def test_ke_toan_forbidden(logged_in: LoggedIn, path: str) -> None:
    assert logged_in(Role.ke_toan).get(path).status_code == 403


@pytest.mark.parametrize("role", [Role.giam_doc, Role.ke_toan])
def test_reports_allowed(logged_in: LoggedIn, role: Role) -> None:
    r = logged_in(role).get("/reports")
    assert r.status_code == 200
    assert "Chưa có dữ liệu báo cáo" in r.text


@pytest.mark.parametrize("path", ["/dashboard", "/dashboard/users", "/reports", "/admin_api/ping"])
def test_anonymous_redirected(client: TestClient, path: str) -> None:
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_admin_ping_json_for_giam_doc(logged_in: LoggedIn) -> None:
    r = logged_in(Role.giam_doc).get("/admin_api/ping")
    assert r.status_code == 200 and r.json() == {"ok": True}


def test_ke_toan_403_on_admin_api_is_json(logged_in: LoggedIn) -> None:
    r = logged_in(Role.ke_toan).get("/admin_api/ping")
    assert r.status_code == 403 and "detail" in r.json()


def test_dashboard_placeholders_default_autonomy(logged_in: LoggedIn) -> None:
    text = logged_in(Role.giam_doc).get("/dashboard").text
    assert "Bài chờ duyệt: 0" in text
    assert "Lead mới: 0" in text
    assert "Mức tự động: draft_only" in text


def test_dashboard_reads_autonomy_setting(logged_in: LoggedIn, db: orm.Session) -> None:
    db.add(Setting(key="AUTONOMY_LEVEL", value="auto_safe"))
    db.commit()
    assert "Mức tự động: auto_safe" in logged_in(Role.giam_doc).get("/dashboard").text


def test_nav_per_role(logged_in: LoggedIn) -> None:
    gd = logged_in(Role.giam_doc).get("/dashboard").text
    for label in ("Bảng điều khiển", "Tài khoản", "Báo cáo", "Đổi mật khẩu", "Đăng xuất"):
        assert label in gd
    kt = logged_in(Role.ke_toan).get("/reports").text
    for label in ("Báo cáo", "Đổi mật khẩu", "Đăng xuất"):
        assert label in kt
    assert "Bảng điều khiển" not in kt and "/dashboard/users" not in kt


def test_dashboard_after_logout_redirects(logged_in: LoggedIn) -> None:
    c = logged_in(Role.giam_doc)
    assert c.get("/dashboard").status_code == 200
    r = c.post("/logout", data={"csrf_token": csrf_of(c)}, follow_redirects=False)
    assert r.status_code == 303
    r = c.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
