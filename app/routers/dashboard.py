import uuid
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import orm, select
from sqlalchemy.exc import IntegrityError

from app.audit import write_audit
from app.auth.csrf import verify_csrf
from app.auth.dependencies import require_role
from app.auth.passwords import hash_password, validate_new_password
from app.auth.session import destroy_user_sessions
from app.db.models import Role, User
from app.db.session import get_db
from app.settings_store import get_autonomy
from app.web import render_page

router = APIRouter(prefix="/dashboard")

USERS_URL = "/dashboard/users"
ALLOWED_ROLES = {Role.giam_doc.value, Role.ke_toan.value}
DUPLICATE_USERNAME = "Tên đăng nhập đã tồn tại"

CurrentGiamDoc = Depends(require_role(Role.giam_doc))


def _users_page(
    request: Request, db: orm.Session, user: User, status_code: int = 200, **context: Any
) -> Response:
    users = list(db.scalars(select(User).order_by(User.created_at, User.username)))
    return render_page(request, "dashboard/users.html", user, status_code, users=users, **context)


@router.get("")
def index(
    request: Request,
    user: User = CurrentGiamDoc,
    db: orm.Session = Depends(get_db),  # noqa: B008
) -> Response:
    return render_page(request, "dashboard/index.html", user, autonomy_level=get_autonomy(db))


@router.get("/users")
def users_page(
    request: Request,
    user: User = CurrentGiamDoc,
    db: orm.Session = Depends(get_db),  # noqa: B008
) -> Response:
    return _users_page(request, db, user)


@router.post("/users", dependencies=[Depends(verify_csrf)])
def create_user(
    request: Request,
    username: str = Form(""),
    full_name: str = Form(""),
    password: str = Form(""),
    role: str = Form(""),
    user: User = CurrentGiamDoc,
    db: orm.Session = Depends(get_db),  # noqa: B008
) -> Response:
    username = username.strip()
    full_name = full_name.strip()
    error: str | None = None
    if not username or len(username) > 100:
        error = "Tên đăng nhập không hợp lệ (1–100 ký tự)"
    elif role not in ALLOWED_ROLES:
        error = "Vai trò không hợp lệ"
    elif len(full_name) > 200:
        error = "Họ tên quá dài"
    else:
        error = validate_new_password(password)
    if error is None and db.scalar(select(User.id).where(User.username == username)) is not None:
        error = DUPLICATE_USERNAME
    if error is None:
        new_user = User(
            username=username,
            full_name=full_name or None,
            password_hash=hash_password(password),
            role=Role(role),
            is_active=True,
        )
        db.add(new_user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            error = DUPLICATE_USERNAME
        else:
            write_audit(
                db,
                user.id,
                "user_created",
                "user",
                str(new_user.id),
                {"username": username, "role": role},
            )
            db.commit()
            return RedirectResponse(USERS_URL, status_code=303)
    return _users_page(
        request,
        db,
        user,
        status_code=400,
        error=error,
        form_username=username,
        form_full_name=full_name,
    )


def _get_target(db: orm.Session, user_id: uuid.UUID) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
    return target


@router.post("/users/{user_id}/toggle-active", dependencies=[Depends(verify_csrf)])
def toggle_active(
    user_id: uuid.UUID,
    user: User = CurrentGiamDoc,
    db: orm.Session = Depends(get_db),  # noqa: B008
) -> Response:
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="Không thể tự vô hiệu hóa tài khoản của mình")
    target = _get_target(db, user_id)
    target.is_active = not target.is_active
    write_audit(
        db,
        user.id,
        "user_activated" if target.is_active else "user_deactivated",
        "user",
        str(target.id),
        {"username": target.username},
    )
    db.commit()
    if not target.is_active:
        destroy_user_sessions(db, target.id)
    return RedirectResponse(USERS_URL, status_code=303)


@router.post("/users/{user_id}/reset-password", dependencies=[Depends(verify_csrf)])
def reset_password(
    request: Request,
    user_id: uuid.UUID,
    new_password: str = Form(""),
    user: User = CurrentGiamDoc,
    db: orm.Session = Depends(get_db),  # noqa: B008
) -> Response:
    if user_id == user.id:
        raise HTTPException(
            status_code=400, detail="Hãy dùng trang Đổi mật khẩu cho tài khoản của mình"
        )
    target = _get_target(db, user_id)
    error = validate_new_password(new_password)
    if error is not None:
        return _users_page(request, db, user, status_code=400, error=error)
    target.password_hash = hash_password(new_password)
    target.failed_attempts = 0
    target.last_failed_at = None
    target.locked_until = None
    write_audit(
        db, user.id, "user_password_reset", "user", str(target.id), {"username": target.username}
    )
    db.commit()
    destroy_user_sessions(db, target.id)
    return RedirectResponse(USERS_URL, status_code=303)
