"""Read-only "Hôm nay" page, served on 127.0.0.1 without login."""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import clock
from app.config import Settings
from app.db.models import Post
from app.posts.store import posts_for_day
from app.schedule_times import LOCAL_TZ, local_now

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
SLOTS = (("morning", "09:00", "Bài sáng"), ("afternoon", "16:30", "Bài chiều"))
STATUS_LABELS = {
    "drafting": "Đang soạn…",
    "pending": "Chờ anh/chị duyệt trên Telegram ⏳",
    "approved": "Đã duyệt – chờ đến giờ đăng",
    "publishing": "Đang đăng…",
    "published": "Đã đăng ✓",
    "rejected": "Đã bỏ",
    "expired": "Hết hạn (không duyệt trước 20:00)",
}
BODY_PREVIEW_CHARS = 300


@dataclass
class SlotView:
    time: str
    name: str
    post: Post | None
    status_label: str
    status: str
    body: str
    source_url: str | None
    source_name: str | None
    image_count: int


def _status_label(post: Post | None) -> str:
    if post is None:
        return "Chưa đến giờ soạn"
    if post.status == "failed":
        return f"Lỗi: {post.error or 'không rõ'}"
    return STATUS_LABELS.get(post.status, post.status)


def _slot_view(post: Post | None, time_: str, name: str) -> SlotView:
    url: str | None = None
    src_name: str | None = None
    if post is not None:
        for source in post.sources:
            candidate = source.get("url", "")
            if candidate.startswith(("http://", "https://")):
                url = candidate
                src_name = source.get("name") or candidate
                break
    return SlotView(
        time=time_,
        name=name,
        post=post,
        status_label=_status_label(post),
        status=post.status if post else "none",
        body=(post.body[:BODY_PREVIEW_CHARS] if post else ""),
        source_url=url,
        source_name=src_name,
        image_count=len(post.image_paths) if post else 0,
    )


def _resolve_media(path_str: str, settings: Settings) -> Path | None:
    picture_dir = Path(settings.PICTURE_DIR).resolve()
    media_dir = (Path(settings.DATA_DIR) / "media").resolve()
    raw = Path(path_str)
    resolved = (raw if raw.is_absolute() else picture_dir / raw).resolve()
    if not (resolved.is_relative_to(picture_dir) or resolved.is_relative_to(media_dir)):
        return None
    return resolved if resolved.is_file() else None


def create_app(
    db_factory: Callable[[], Session],
    settings: Settings,
    now_fn: Callable[[], datetime] = clock.utcnow,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def today(request: Request) -> HTMLResponse:
        now = local_now(now_fn()).astimezone(LOCAL_TZ)
        day = now.date()
        with db_factory() as db:
            by_slot = {p.slot: p for p in posts_for_day(db, day)}
            slots = [_slot_view(by_slot.get(s), t, n) for s, t, n in SLOTS]
            return TEMPLATES.TemplateResponse(
                request,
                "today.html",
                {
                    "weekday": WEEKDAYS[day.weekday()],
                    "date_text": day.strftime("%d/%m/%Y"),
                    "dry_run": settings.DRY_RUN,
                    "slots": slots,
                },
            )

    @app.get("/media/{post_id}/{index}")
    def media(post_id: uuid.UUID, index: int) -> FileResponse:
        with db_factory() as db:
            post = db.get(Post, post_id)
            paths = list(post.image_paths) if post else []
        if index < 0 or index >= len(paths):
            raise HTTPException(status_code=404)
        resolved = _resolve_media(paths[index], settings)
        if resolved is None:
            raise HTTPException(status_code=404)
        return FileResponse(resolved)

    return app
