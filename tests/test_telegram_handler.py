from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Alert, Post
from app.llm.client import FakeLLM, LLMError
from app.posts import store
from app.schedule_times import Slot
from app.telegram import handler
from app.telegram.bot import FakeTelegram, TelegramError
from app.telegram.handler import get_offset, handle_update, poll_once, set_offset
from tests.test_post_store import REPORT, D, draft, local
from tests.test_writer import _draft, _verdict

ADMIN = "1"
NOW = local(D, 8, 30)


def make_pending(db: Session, slot: Slot = "morning", message_id: int | None = 50) -> Post:
    post = store.claim_slot(db, D, slot)
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)
    post.telegram_message_id = message_id
    db.commit()
    return post


def button(post: Post, kind: str, revision: int | None = None, chat: int = 1) -> dict[str, Any]:
    return {
        "update_id": 1,
        "callback_query": {
            "id": "cb1",
            "data": f"{kind}:{post.id}:{revision or post.revision}",
            "message": {"message_id": 50, "chat": {"id": chat}},
        },
    }


def text(msg: str, reply_to: int | None = None, chat: int = 1) -> dict[str, Any]:
    message: dict[str, Any] = {"message_id": 7, "chat": {"id": chat}, "text": msg}
    if reply_to is not None:
        message["reply_to_message"] = {"message_id": reply_to}
    return {"update_id": 2, "message": message}


def texts(bot: FakeTelegram, method: str = "send_message") -> list[str]:
    return [s["text"] for s in bot.sent if s["method"] == method]


def test_ignores_other_chats(db: Session) -> None:
    post = make_pending(db)
    bot = FakeTelegram()
    handle_update(db, bot, None, button(post, "ok", chat=999), NOW, ADMIN)
    handle_update(db, bot, None, text("sửa đi", chat=999), NOW, ADMIN)
    assert bot.sent == []
    assert post.status == "pending"


def test_approve_button_approves_and_removes_keyboard(db: Session) -> None:
    post = make_pending(db)
    bot = FakeTelegram()
    handle_update(db, bot, None, button(post, "ok"), NOW, ADMIN)
    assert post.status == "approved"
    assert texts(bot, "answer_callback") == ["Đã duyệt. Bài sẽ đăng lúc 09:00."]
    assert {"method": "edit_buttons_removed", "message_id": 50} in bot.sent


def test_approve_after_slot_time_says_now(db: Session) -> None:
    post = make_pending(db)
    bot = FakeTelegram()
    handle_update(db, bot, None, button(post, "ok"), local(D, 10, 0), ADMIN)
    assert texts(bot, "answer_callback") == ["Đã duyệt. Bài sẽ đăng ngay."]


def test_reject_button(db: Session) -> None:
    post = make_pending(db)
    bot = FakeTelegram()
    handle_update(db, bot, None, button(post, "no"), NOW, ADMIN)
    assert post.status == "rejected"
    assert texts(bot, "answer_callback") == ["Đã bỏ bài này."]
    assert {"method": "edit_buttons_removed", "message_id": 50} in bot.sent


def test_old_revision_button_is_stale(db: Session) -> None:
    post = make_pending(db)
    store.new_revision(db, post, draft("v2"), REPORT, False)
    bot = FakeTelegram()
    handle_update(db, bot, None, button(post, "ok", revision=1), NOW, ADMIN)
    assert post.status == "pending"
    assert texts(bot, "answer_callback") == [handler.TXT_STALE]


def test_button_after_published_is_stale(db: Session) -> None:
    post = make_pending(db)
    post.status = "published"
    db.commit()
    bot = FakeTelegram()
    handle_update(db, bot, None, button(post, "ok"), NOW, ADMIN)
    handle_update(db, bot, None, button(post, "no"), NOW, ADMIN)
    assert post.status == "published"
    assert texts(bot, "answer_callback") == [handler.TXT_STALE, handler.TXT_STALE]


def test_blocked_post_cannot_be_approved(db: Session) -> None:
    post = make_pending(db)
    post.blocking = True
    db.commit()
    bot = FakeTelegram()
    handle_update(db, bot, None, button(post, "ok"), NOW, ADMIN)
    assert post.status == "pending"
    assert texts(bot, "answer_callback") == [handler.TXT_BLOCKED]


def test_malformed_callback_data(db: Session) -> None:
    bot = FakeTelegram()
    upd = {
        "update_id": 1,
        "callback_query": {
            "id": "c",
            "data": "garbage",
            "message": {"message_id": 1, "chat": {"id": 1}},
        },
    }
    handle_update(db, bot, None, upd, NOW, ADMIN)
    assert texts(bot, "answer_callback") == ["Nút không hợp lệ."]


def test_feedback_reply_creates_new_revision_and_resends(db: Session) -> None:
    post = make_pending(db)
    llm = FakeLLM({"content": [_draft(title="Bản mới")], "guardrail_judge": [_verdict()]})
    bot = FakeTelegram()
    handle_update(db, bot, llm, text("Ngắn gọn hơn", reply_to=50), NOW, ADMIN)
    assert post.revision == 2 and post.status == "pending" and post.title == "Bản mới"
    assert post.telegram_message_id == 101  # 100 was "Đang sửa…", 101 the review message
    assert texts(bot)[0] == handler.TXT_REVISING
    sent = [s for s in bot.sent if s["method"] == "send_message"][-1]
    assert sent["buttons"] and sent["buttons"][0][1] == f"ok:{post.id}:2"
    assert {"method": "edit_buttons_removed", "message_id": 50} in bot.sent
    assert "Ngắn gọn hơn" in llm.calls[0]["user"]


def test_single_pending_free_text_is_applied(db: Session) -> None:
    post = make_pending(db)
    llm = FakeLLM({"content": [_draft(title="X")], "guardrail_judge": [_verdict()]})
    handle_update(db, FakeTelegram(), llm, text("đổi tiêu đề"), NOW, ADMIN)
    assert post.revision == 2


def test_free_text_with_two_pending_asks_to_reply(db: Session) -> None:
    make_pending(db, "morning", 50)
    make_pending(db, "afternoon", 51)
    llm = FakeLLM({})
    bot = FakeTelegram()
    handle_update(db, bot, llm, text("sửa lại"), NOW, ADMIN)
    assert texts(bot) == [handler.TXT_MANY_PENDING]
    assert llm.calls == []
    assert all(p.revision == 1 for p in db.scalars(select(Post)))


def test_text_with_nothing_pending(db: Session) -> None:
    bot = FakeTelegram()
    handle_update(db, bot, FakeLLM({}), text("/start"), NOW, ADMIN)
    handle_update(db, bot, FakeLLM({}), text("hello"), NOW, ADMIN)
    assert texts(bot) == [handler.TXT_NONE_PENDING] * 2


def test_feedback_without_llm(db: Session) -> None:
    post = make_pending(db)
    bot = FakeTelegram()
    handle_update(db, bot, None, text("sửa"), NOW, ADMIN)
    assert texts(bot) == [handler.TXT_NO_LLM]
    assert post.revision == 1


def test_feedback_llm_error_keeps_post(db: Session) -> None:
    post = make_pending(db)
    llm = FakeLLM({"content": [LLMError("api", "x")]})
    bot = FakeTelegram()
    handle_update(db, bot, llm, text("sửa"), NOW, ADMIN)
    assert texts(bot) == [handler.TXT_REVISING, handler.TXT_LLM_FAILED]
    assert post.revision == 1 and post.status == "pending"


def test_offset_roundtrip(db: Session) -> None:
    assert get_offset(db) == 0
    set_offset(db, 5)
    set_offset(db, 9)
    assert get_offset(db) == 9


def settings() -> Settings:
    return Settings(_env_file=None, TELEGRAM_ADMIN_CHAT_ID=ADMIN)  # type: ignore[call-arg]


def test_offset_advances_per_update_even_when_handler_fails(
    db_factory: Callable[[], Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(handler, "handle_update", boom)
    bot = FakeTelegram()
    bot.updates = [{"update_id": 10, "message": {}}, {"update_id": 11, "message": {}}]
    poll_once(db_factory, bot, None, settings(), lambda: NOW)
    with db_factory() as db:
        assert get_offset(db) == 12
        alerts = [a.message for a in db.scalars(select(Alert))]
    assert alerts == ["Lỗi xử lý tin Telegram: RuntimeError"] * 2


def test_poll_once_handles_update_and_skips_old(db_factory: Callable[[], Session]) -> None:
    with db_factory() as db:
        post = make_pending(db)
        set_offset(db, 2)
    bot = FakeTelegram()
    bot.updates = [dict(button(post, "ok"), update_id=1), dict(button(post, "ok"), update_id=2)]
    poll_once(db_factory, bot, None, settings(), lambda: NOW)
    with db_factory() as db:
        assert db.get(Post, post.id).status == "approved"  # type: ignore[union-attr]
        assert get_offset(db) == 3


def test_poll_once_returns_on_telegram_error(db_factory: Callable[[], Session]) -> None:
    class Broken(FakeTelegram):
        def get_updates(self, offset: int, timeout: int = 30) -> list[dict[str, Any]]:
            raise TelegramError("getUpdates failed")

    poll_once(db_factory, Broken(), None, settings(), lambda: NOW)
    with db_factory() as db:
        assert get_offset(db) == 0
