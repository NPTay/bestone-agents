from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import orm

from app.auth.session import resolve_session
from app.config import get_settings
from app.db.models import Role, User
from app.db.session import get_db


class LoginRequired(Exception):
    """Raised when no valid session exists; handled in main.py as a 303 to /login."""


def require_login(request: Request, db: orm.Session = Depends(get_db)) -> User:  # noqa: B008
    token = request.cookies.get(get_settings().SESSION_COOKIE_NAME)
    user = resolve_session(db, token)
    if user is None:
        raise LoginRequired
    request.state.user = user
    return user


def require_role(*roles: Role) -> Callable[..., User]:
    def checker(user: User = Depends(require_login)) -> User:  # noqa: B008
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Không có quyền truy cập")
        return user

    return checker
