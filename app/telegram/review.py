import logging
from typing import Protocol

from sqlalchemy.orm import Session

from app.db.models import Post
from app.integrations.notify import send_alert
from app.telegram.bot import TelegramError

logger = logging.getLogger(__name__)

MAX_LEN = 4000
SLOT_LABEL = {"morning": "SÁNG", "afternoon": "CHIỀU"}
SLOT_TIME = {"morning": "09:00", "afternoon": "16:30"}
FOOTER = "💬 Muốn sửa: trả lời (reply) tin nhắn này và gõ góp ý."
BLOCKING_NOTICE = "⛔ Bài có lỗi thông tin nên chưa thể đăng. Hãy góp ý để AI sửa."


class _Bot(Protocol):
    def send_message(
        self,
        text: str,
        buttons: list[tuple[str, str]] | None = None,
        reply_to: int | None = None,
    ) -> int: ...

    def send_photos(self, paths: list[str]) -> None: ...


def _compose(post: Post, body: str) -> str:
    header = (
        f"📝 BÀI {SLOT_LABEL[post.slot]} {post.day:%d/%m} — "
        f"đăng lúc {SLOT_TIME[post.slot]} (bản {post.revision})"
    )
    parts = [header, post.title, body, f"{post.cta}\n{' '.join(post.hashtags or [])}"]
    tail: list[str] = []
    if post.sources:
        tail.append("Nguồn: " + "\n".join(f"{s['name']} – {s['url']}" for s in post.sources))
    if post.image_note:
        tail.append(post.image_note)
    flags = (post.guardrail_report or {}).get("flags") or []
    if flags:
        tail.append("⚠️ Cần xem: " + "; ".join(flags))
    if post.blocking:
        tail.append(BLOCKING_NOTICE)
    text = "\n\n".join(parts)
    if tail:
        text += "\n\n" + "\n".join(tail)
    return text + "\n\n" + FOOTER


def format_review(post: Post) -> str:
    body = post.body
    overflow = len(_compose(post, body)) - MAX_LEN
    if overflow > 0:
        keep = max(len(body) - overflow - 1, 0)
        body = body[:keep] + "…"
    return _compose(post, body)


def _buttons(post: Post) -> list[tuple[str, str]]:
    buttons = [("❌ Không đăng", f"no:{post.id}:{post.revision}")]
    if not post.blocking:
        buttons.insert(0, ("✅ Đăng", f"ok:{post.id}:{post.revision}"))
    return buttons


def send_for_review(bot: _Bot, post: Post) -> int:
    """Send photos (if any) then the review text with approve/reject buttons."""
    if post.image_paths:
        bot.send_photos(list(post.image_paths))
    return bot.send_message(format_review(post), buttons=_buttons(post))


def send_for_review_safe(
    bot: _Bot, post: Post, db: Session, alert_text: str | None = None
) -> int | None:
    """Send for review; retry once, then fall back to plain text, then alert.

    Returns the Telegram message id, or None when nothing could be sent.
    """
    for _ in range(2):
        try:
            return send_for_review(bot, post)
        except (TelegramError, OSError) as exc:
            logger.warning("Sending post for review failed: %s", type(exc).__name__)
    try:
        return bot.send_message(format_review(post), buttons=_buttons(post))
    except (TelegramError, OSError) as exc:
        logger.warning("Plain-text review fallback failed: %s", type(exc).__name__)
    slot = "sáng" if post.slot == "morning" else "chiều"
    send_alert(db, "warn", alert_text or f"Không gửi được bài {slot} lên Telegram.")
    return None
