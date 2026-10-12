from fastapi import FastAPI

from app.config import Settings, get_settings
from app.routers import health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Bestone Agents", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.include_router(health.router)
    return app
