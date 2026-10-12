from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from app.auth.dependencies import LoginRequired
from app.config import Settings, get_settings
from app.routers import health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Bestone Agents", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.include_router(health.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired) -> RedirectResponse:
        return RedirectResponse("/login", status_code=303)

    return app
