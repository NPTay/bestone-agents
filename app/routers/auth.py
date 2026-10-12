from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import orm

from app.audit import write_audit
from app.auth.csrf import ensure_csrf_cookie, rotate_csrf_cookie, verify_csrf
from app.auth.dependencies import require_login
from app.auth.passwords import hash_password, validate_new_password, verify_password
from app.auth.ratelimit import login_limiter
from app.auth.service import authenticate, format_local_time
from app.auth.session import (
    clear_session_cookie,
    create_session,
    destroy_session,
    destroy_user_sessions,
    resolve_session,
    set_session_cookie,
)
from app.config import get_settings
from app.db.models import Role, User
from app.db.session import get_db
from app.templates import templates
from app.web import render_page

router = APIRouter()

GENERIC_ERROR = "Sai tên đăng nhập hoặc mật khẩu"
RATE_LIMIT_MESSAGE = "Quá nhiều lần thử, vui lòng đợi 1 phút"

ROLE_HOME = {Role.giam_doc: "/dashboard", Role.ke_toan: "/reports"}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _render(request: Request, name: str, status_code: int = 200, **context: Any) -> Response:
    """Render a template and attach the CSRF cookie (set only if not already present)."""
    holder = Response()
    token = ensure_csrf_cookie(request, holder)
    response = templates.TemplateResponse(
        request, name, {**context, "csrf_token": token}, status_code=status_code
    )
    for cookie in holder.headers.getlist("set-cookie"):
        response.headers.append("set-cookie", cookie)
    return response


def limit_login_rate(request: Request) -> None:
    """Runs before CSRF so token-less floods are throttled too."""
    if not login_limiter.hit(_client_ip(request)):
        raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)


@router.get("/login")
def login_page(request: Request, db: orm.Session = Depends(get_db)) -> Response:  # noqa: B008
    user = resolve_session(db, request.cookies.get(get_settings().SESSION_COOKIE_NAME))
    if user is not None:
        return RedirectResponse(ROLE_HOME[user.role], status_code=303)
    return _render(request, "login.html")


@router.post("/login", dependencies=[Depends(limit_login_rate), Depends(verify_csrf)])
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    remember_me: str | None = Form(None),
    db: orm.Session = Depends(get_db),  # noqa: B008
) -> Response:
    result = authenticate(db, username, password)
    if result.user is None:
        if result.error == "locked" and result.locked_until is not None:
            message = f"Tài khoản tạm khóa, thử lại sau {format_local_time(result.locked_until)}"
        else:
            message = GENERIC_ERROR
        return _render(request, "login.html", error=message)

    remember = remember_me is not None
    token = create_session(
        db,
        result.user,
        remember,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    response = RedirectResponse(ROLE_HOME[result.user.role], status_code=303)
    set_session_cookie(response, token, remember)
    rotate_csrf_cookie(response)
    return response


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(
    request: Request,
    user: User = Depends(require_login),  # noqa: B008
    db: orm.Session = Depends(get_db),  # noqa: B008
) -> Response:
    write_audit(db, user.id, "logout", "user", str(user.id), {})
    db.commit()
    token = request.cookies.get(get_settings().SESSION_COOKIE_NAME)
    if token:
        destroy_session(db, token)
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    rotate_csrf_cookie(response)
    return response


@router.get("/account/change-password")
def change_password_page(
    request: Request,
    user: User = Depends(require_login),  # noqa: B008
) -> Response:
    return render_page(request, "change_password.html", user)


@router.post("/account/change-password", dependencies=[Depends(verify_csrf)])
def change_password_submit(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    user: User = Depends(require_login),  # noqa: B008
    db: orm.Session = Depends(get_db),  # noqa: B008
) -> Response:
    error: str | None = None
    if not verify_password(user.password_hash, current_password):
        error = "Mật khẩu hiện tại không đúng"
    elif new_password != confirm_password:
        error = "Mật khẩu mới và phần nhập lại không khớp"
    else:
        error = validate_new_password(new_password)
    if error is not None:
        return render_page(request, "change_password.html", user, status_code=400, error=error)
    user.password_hash = hash_password(new_password)
    user.failed_attempts = 0
    user.last_failed_at = None
    user.locked_until = None
    write_audit(db, user.id, "password_changed", "user", str(user.id), {})
    db.commit()
    destroy_user_sessions(
        db, user.id, except_token=request.cookies.get(get_settings().SESSION_COOKIE_NAME)
    )
    return render_page(request, "change_password.html", user, success="Đã đổi mật khẩu")
