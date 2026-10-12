from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth.dependencies import LoginRequired
from app.config import Settings, get_settings
from app.routers import auth, health
from app.templates import templates


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Bestone Agents", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(auth.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired) -> RedirectResponse:
        return RedirectResponse("/login", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith(("/admin_api/", "/webhook/")):
            return JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
            )
        detail = exc.detail if isinstance(exc.detail, str) else "Đã xảy ra lỗi"
        if detail.startswith("CSRF"):
            detail = "Phiên biểu mẫu không hợp lệ hoặc đã hết hạn, vui lòng tải lại trang"
        elif exc.status_code == 404:
            detail = "Không tìm thấy trang"
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    return app
