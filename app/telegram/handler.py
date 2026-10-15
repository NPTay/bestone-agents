"""Turn Telegram updates (button presses, feedback text) into post state changes."""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.content.pictures import parse_projects
from app.content.writer import review, revise
from app.db.models import Post, Setting
from app.integrations.notify import send_alert
from app.llm.client import LLMClient, LLMError
from app.llm.prompts import load_knowledge
from app.posts import store
from app.posts.store import PostDraft
from app.schedule_times import local_now
from app.telegram.bot import TelegramError
from app.telegram.review import send_for_review_safe

logger = logging.getLogger(__name__)

OFFSET_KEY = "TELEGRAM_OFFSET"

TXT_NONE_PENDING = "Hiện không có bài nào đang chờ duyệt."
TXT_MANY_PENDING = (
    "Có nhiều bài đang chờ. Anh/chị hãy trả lời (reply) đúng tin nhắn của bài cần sửa."
)
TXT_STALE = "Nút này đã cũ (bài đã có bản mới hoặc đã xử lý)."
TXT_BLOCKED = "Bài có lỗi thông tin, chưa thể đăng. Hãy góp ý để AI sửa."
TXT_BAD_BUTTON = "Nút không hợp lệ."
TXT_REJECTED = "Đã bỏ bài này."
TXT_APPROVED = "Đã duyệt. Bài đang được đăng lên Fanpage."
TXT_REVISING = "Đang sửa theo góp ý…"
TXT_NO_LLM = "AI chưa được cấu hình nên chưa sửa được bài."
TXT_LLM_FAILED = "Sửa bài bị lỗi, anh/chị thử gõ lại góp ý sau ít phút."
TXT_SEND_FAILED = "Không gửi được bản sửa lên Telegram. Hãy gõ lại góp ý để thử lại."


class _Bot(Protocol):
    def send_message(
        self,
        text: str,
        buttons: list[tuple[str, str]] | None = None,
        reply_to: int | None = None,
    ) -> int: ...

    def send_photos(self, paths: list[str]) -> None: ...

    def answer_callback(self, callback_id: str, text: str) -> None: ...

    def edit_buttons_removed(self, message_id: int) -> None: ...

    def get_updates(self, offset: int, timeout: int = 30) -> list[dict[str, Any]]: ...


def get_offset(db: Session) -> int:
    row = db.scalar(select(Setting).where(Setting.key == OFFSET_KEY))
    return int(row.value) if row is not None else 0


def set_offset(db: Session, value: int) -> None:
    row = db.scalar(select(Setting).where(Setting.key == OFFSET_KEY))
    if row is None:
        db.add(Setting(key=OFFSET_KEY, value=str(value)))
    else:
        row.value = str(value)
    db.commit()


def _parse_button(data: str) -> tuple[str, uuid.UUID, int] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] not in ("ok", "no"):
        return None
    try:
        return parts[0], uuid.UUID(parts[1]), int(parts[2])
    except ValueError:
        return None


def _pending_today(db: Session, now: datetime) -> list[Post]:
    return [p for p in store.posts_for_day(db, local_now(now).date()) if p.status == "pending"]


def _handle_callback(
    db: Session,
    bot: _Bot,
    cq: dict[str, Any],
    now: datetime,
    on_approved: Callable[[], None] | None = None,
) -> None:
    callback_id = str(cq.get("id", ""))
    parsed = _parse_button(str(cq.get("data", "")))
    if parsed is None:
        bot.answer_callback(callback_id, TXT_BAD_BUTTON)
        return
    action, post_id, revision = parsed
    message_id = int(cq["message"]["message_id"])
    if action == "ok":
        result = store.approve(db, post_id, revision, now)
        if result == "stale":
            bot.answer_callback(callback_id, TXT_STALE)
        elif result == "blocked":
            bot.answer_callback(callback_id, TXT_BLOCKED)
        else:
            bot.answer_callback(callback_id, TXT_APPROVED)
            bot.edit_buttons_removed(message_id)
            if on_approved is not None:
                on_approved()  # wake the tick thread so it publishes now
        return
    if store.reject(db, post_id, revision) == "ok":
        bot.answer_callback(callback_id, TXT_REJECTED)
        bot.edit_buttons_removed(message_id)
    else:
        bot.answer_callback(callback_id, TXT_STALE)


def _target_post(db: Session, bot: _Bot, message: dict[str, Any], now: datetime) -> Post | None:
    """The pending post the feedback is about; explains and returns None otherwise."""
    pending = _pending_today(db, now)
    reply = message.get("reply_to_message")
    if isinstance(reply, dict) and "message_id" in reply:
        target = db.scalar(
            select(Post).where(
                Post.telegram_message_id == int(reply["message_id"]),
                Post.status == "pending",
            )
        )
        if target is not None:
            return target
        # A reply to something else: never guess which post is meant.
        bot.send_message(TXT_MANY_PENDING if pending else TXT_NONE_PENDING)
        return None
    if len(pending) == 1:
        return pending[0]
    bot.send_message(TXT_MANY_PENDING if len(pending) > 1 else TXT_NONE_PENDING)
    return None


def _handle_text(
    db: Session, bot: _Bot, llm: LLMClient | None, message: dict[str, Any], now: datetime
) -> None:
    text = str(message.get("text", "")).strip()
    if not text:
        return
    if text.startswith("/"):
        is_start = text.split()[0].split("@")[0] == "/start"
        if is_start and not _pending_today(db, now):
            bot.send_message(TXT_NONE_PENDING)
        return
    post = _target_post(db, bot, message, now)
    if post is None:
        return
    if llm is None:
        bot.send_message(TXT_NO_LLM)
        return
    bot.send_message(TXT_REVISING)
    kb = load_knowledge()["bestone_knowledge_base.md"]
    sources = [post.source_text] if post.source_text else []
    unverified = [name for name, info in parse_projects(kb).items() if not info.verified]
    previous = PostDraft(
        title=post.title or "",
        body=post.body,
        hashtags=post.hashtags,
        cta=post.cta or "",
        sources=post.sources,
        kb_refs=post.kb_refs,
    )
    try:
        draft = revise(llm, previous, text, kb, sources, None)
        report, blocking = review(llm, draft, kb, sources, unverified, None)
    except LLMError:
        bot.send_message(TXT_LLM_FAILED)
        return
    old_message_id = post.telegram_message_id
    store.new_revision(db, post, draft, report, blocking)
    new_message_id = send_for_review_safe(bot, post, db, TXT_SEND_FAILED)
    if new_message_id is None:
        return
    post.telegram_message_id = new_message_id
    db.commit()
    if old_message_id is not None:
        bot.edit_buttons_removed(old_message_id)


def handle_update(
    db: Session,
    bot: _Bot,
    llm: LLMClient | None,
    update: dict[str, Any],
    now: datetime,
    admin_chat_id: str,
    on_approved: Callable[[], None] | None = None,
) -> None:
    cq = update.get("callback_query")
    if isinstance(cq, dict):
        chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
        if chat_id is None or str(chat_id) != str(admin_chat_id):
            return
        _handle_callback(db, bot, cq, now, on_approved)
        return
    message = update.get("message")
    if isinstance(message, dict):
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id is None or str(chat_id) != str(admin_chat_id):
            return
        _handle_text(db, bot, llm, message, now)


def poll_once(
    db_factory: Callable[[], Session],
    bot: _Bot,
    llm: LLMClient | None,
    settings: Settings,
    now_fn: Callable[[], datetime],
    on_approved: Callable[[], None] | None = None,
) -> None:
    """Fetch and handle pending updates; the offset advances after each one."""
    with db_factory() as db:
        offset = get_offset(db)
    try:
        updates = bot.get_updates(offset)
    except TelegramError as exc:
        logger.warning("Telegram getUpdates failed: %s", type(exc).__name__)
        return
    for update in updates:
        with db_factory() as db:
            try:
                handle_update(
                    db,
                    bot,
                    llm,
                    update,
                    now_fn(),
                    str(settings.TELEGRAM_ADMIN_CHAT_ID),
                    on_approved,
                )
            except Exception as exc:
                db.rollback()
                logger.error("Telegram update handling failed: %s", type(exc).__name__)
                send_alert(db, "warn", f"Lỗi xử lý tin Telegram: {type(exc).__name__}")
            set_offset(db, int(update["update_id"]) + 1)
