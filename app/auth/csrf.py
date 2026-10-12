import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request, Response

from app.auth.session import cookie_secure
from app.config import get_settings

CSRF_COOKIE = "bestone_csrf"
CSRF_FIELD = "csrf_token"


def _form_token(cookie_value: str) -> str:
    key = get_settings().SESSION_SECRET_KEY.encode()
    return hmac.new(key, cookie_value.encode(), hashlib.sha256).hexdigest()


def form_token_for(cookie_value: str) -> str:
    """Public accessor: the form token that matches a given CSRF cookie value."""
    return _form_token(cookie_value)


def _set_csrf_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        value,
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )


def rotate_csrf_cookie(response: Response) -> str:
    """Issue a fresh CSRF cookie (login/logout, anti cookie-tossing); return its form token."""
    value = secrets.token_urlsafe(32)
    _set_csrf_cookie(response, value)
    return _form_token(value)


def ensure_csrf_cookie(request: Request, response: Response) -> str:
    """Set the CSRF cookie if absent; return the form token derived from it."""
    value = request.cookies.get(CSRF_COOKIE)
    if not value:
        value = secrets.token_urlsafe(32)
        _set_csrf_cookie(response, value)
    return _form_token(value)


async def verify_csrf(request: Request) -> None:
    """FastAPI dependency for state-changing form POSTs; raises 403 on any mismatch."""
    cookie_value = request.cookies.get(CSRF_COOKIE)
    if not cookie_value:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    form = await request.form()
    submitted = form.get(CSRF_FIELD)
    if not isinstance(submitted, str) or not submitted:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not hmac.compare_digest(submitted, _form_token(cookie_value)):
        raise HTTPException(status_code=403, detail="CSRF token invalid")
