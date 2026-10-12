from typing import Any

from fastapi import Request, Response

from app.auth.csrf import ensure_csrf_cookie
from app.db.models import User
from app.templates import templates


def render_page(
    request: Request, name: str, user: User, status_code: int = 200, **context: Any
) -> Response:
    """Render an authenticated page: injects user + CSRF token, sets the CSRF cookie if absent."""
    holder = Response()
    token = ensure_csrf_cookie(request, holder)
    response = templates.TemplateResponse(
        request,
        name,
        {**context, "user": user, "csrf_token": token},
        status_code=status_code,
    )
    for cookie in holder.headers.getlist("set-cookie"):
        response.headers.append("set-cookie", cookie)
    return response
