"""Publish approved posts to the Facebook Page, plus the fixed promo comment."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.content.pictures import record_use
from app.db.models import Post
from app.integrations.notify import send_alert
from app.meta.graph import GraphClient, GraphError
from app.schedule_times import local_now
from app.telegram.bot import TelegramError

logger = logging.getLogger(__name__)

COMMENT_TEXT = (
    "Bestone – phụ gia cho bê tông tự chống thấm.\n"
    "📞 Hotline: 0904834577\n"
    "🌐 Website: https://cgengvn.com"
)
TOKEN_EXPIRED_TEXT = "Token Facebook hết hạn hoặc bị thu hồi. Cần lấy token mới (xem hướng dẫn)."
DRY_RUN_ID = "DRY_RUN"


class _Messenger(Protocol):
    def send_message(self, text: str) -> int: ...


def _slot_vi(post: Post) -> str:
    return "sáng" if post.slot == "morning" else "chiều"


def compose_message(post: Post) -> str:
    parts = [post.title.strip(), post.body.strip(), post.cta.strip()]
    hashtags = " ".join(h if h.startswith("#") else f"#{h}" for h in post.hashtags)
    parts.append(hashtags)
    if post.slot == "morning":
        lines = [f"Nguồn: {s.get('name', '')} – {s.get('url', '')}" for s in post.sources]
        parts.append("\n".join(lines))
    return "\n\n".join(p for p in parts if p)


def _notify(bot: _Messenger, text: str) -> None:
    try:
        bot.send_message(text)
    except (TelegramError, httpx.HTTPError) as exc:
        logger.warning("Telegram notification failed: %s", type(exc).__name__)


def _relative_picture_paths(post: Post) -> list[str]:
    root = Path(get_settings().PICTURE_DIR).resolve()
    rel: list[str] = []
    for raw in post.image_paths:
        try:
            rel.append(Path(raw).resolve().relative_to(root).as_posix())
        except ValueError:
            continue  # not under PICTURE_DIR (e.g. morning media)
    return rel


def _record_picture_use(db: Session, post: Post, now: datetime) -> None:
    if post.slot != "afternoon":
        return
    paths = _relative_picture_paths(post)
    if paths:
        record_use(db, paths, now)


def _fail(db: Session, post: Post, error: str) -> None:
    post.status = "failed"
    post.error = error
    db.commit()


def publish_post(
    db: Session,
    graph: GraphClient | None,
    bot: _Messenger,
    post: Post,
    now: datetime,
    dry_run: bool,
) -> None:
    slot = _slot_vi(post)
    if graph is None and not dry_run:
        _fail(db, post, "Chưa cấu hình Facebook")
        send_alert(db, "warn", f"Đăng bài {slot} thất bại: Chưa cấu hình Facebook")
        return

    # Commit BEFORE touching Graph: a crash after this leaves `publishing`,
    # which is never retried automatically (see recover_stuck).
    post.status = "publishing"
    db.commit()

    if dry_run or graph is None:
        post.status = "published"
        post.published_at = now
        post.fb_post_id = DRY_RUN_ID
        post.comment_id = DRY_RUN_ID
        db.commit()
        _record_picture_use(db, post, now)
        _notify(bot, f"🧪 (Chạy thử) Đã giả lập đăng bài {slot}.")
        return

    try:
        fb_post_id = graph.publish(compose_message(post), list(post.image_paths))
    except GraphError as exc:
        _fail(db, post, exc.message)
        if exc.code == 190:
            send_alert(db, "urgent", TOKEN_EXPIRED_TEXT)
        else:
            send_alert(db, "warn", f"Đăng bài {slot} thất bại: {exc.message}")
        return
    except OSError as exc:
        _fail(db, post, f"Không đọc được ảnh: {type(exc).__name__}")
        send_alert(db, "warn", f"Đăng bài {slot} thất bại: không đọc được ảnh")
        return

    post.status = "published"
    post.published_at = now
    post.fb_post_id = fb_post_id
    db.commit()
    _record_picture_use(db, post, now)
    _try_comment(db, graph, post)
    _notify(bot, f"✅ Đã đăng bài {slot}.")


def _try_comment(db: Session, graph: GraphClient, post: Post) -> None:
    if not post.fb_post_id:
        return
    try:
        post.comment_id = graph.comment(post.fb_post_id, COMMENT_TEXT)
    except GraphError as exc:
        logger.warning("Promo comment failed (code %s); will retry", exc.code)
        return
    db.commit()


def retry_missing_comments(db: Session, graph: GraphClient | None, now: datetime) -> None:
    if graph is None:
        return
    today = local_now(now).date()
    posts = db.scalars(
        select(Post).where(
            Post.status == "published",
            Post.day == today,
            Post.fb_post_id.is_not(None),
            Post.comment_id.is_(None),
        )
    ).all()
    for post in posts:
        if post.fb_post_id == DRY_RUN_ID:
            continue
        _try_comment(db, graph, post)


def recover_stuck(db: Session, bot: _Messenger | None = None) -> None:
    """Mark posts left in `publishing` as failed. Never republishes."""
    stuck = db.scalars(select(Post).where(Post.status == "publishing")).all()
    for post in stuck:
        post.status = "failed"
        post.error = "Bị gián đoạn khi đang đăng"
        db.commit()
        send_alert(
            db,
            "urgent",
            f"Bài {_slot_vi(post)} {post.day:%d/%m} bị gián đoạn lúc đang đăng. "
            "Hãy mở Fanpage kiểm tra xem bài đã lên chưa — chương trình sẽ KHÔNG tự đăng lại "
            "để tránh trùng.",
        )
