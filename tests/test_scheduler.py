from collections.abc import Callable, Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import scheduler
from app.config import Settings, get_settings
from app.content.images import ImagePlan, ImageResult
from app.content.research import Article
from app.db.models import Alert, Post, ResearchItem, Setting
from app.llm.client import FakeLLM
from app.meta.graph import GraphClient
from app.posts import store
from app.schedule_times import Slot
from app.scheduler import Deps, startup, tick
from app.telegram.bot import FakeTelegram
from tests.test_post_store import REPORT, D, draft, local
from tests.test_writer import ARTICLE, _draft, _morning, _verdict

SessionFactory = Callable[[], Session]


@pytest.fixture
def dirs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    pictures = tmp_path / "Picture"
    pictures.mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("PICTURE_DIR", str(pictures))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


class Calls:
    def __init__(self) -> None:
        self.research = 0
        self.images = 0
        self.fail_research = 0  # next N research calls raise (network down)


def make_deps(
    db_factory: SessionFactory,
    tmp: Path,
    llm: FakeLLM | None,
    bot: FakeTelegram,
    calls: Calls,
    articles: list[Article] | None = None,
) -> Deps:
    found = [ARTICLE] if articles is None else articles

    def research(
        llm: Any, db: Session, queries: list[str], job_id: Any, **kw: Any
    ) -> list[Article]:
        calls.research += 1
        if calls.fail_research > 0:
            calls.fail_research -= 1
            raise OSError("network down")
        assert queries, "queries come from config/research_queries.txt"
        for a in found:
            db.add(
                ResearchItem(
                    url=a.url, title=a.title, source_name=a.source_name, fetched_at=local(D, 8)
                )
            )
        db.commit()
        return list(found)

    def image(plan: ImagePlan, dest_dir: Path, settings: Settings) -> ImageResult:
        calls.images += 1
        assert dest_dir == Path(settings.DATA_DIR) / "media"
        return ImageResult(paths=[str((dest_dir / "m.jpg").resolve())], note="Ảnh: Jane / Unsplash")

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        PICTURE_DIR=str(tmp / "Picture"),
        DATA_DIR=str(tmp / "data"),
        DRY_RUN=True,
    )
    return Deps(
        db_factory=db_factory,
        llm=llm,
        bot=bot,
        graph=None,
        settings=settings,
        image_fn=image,
        research_fn=research,
        max_attempts=1,
        sleep=lambda _s: None,
    )


class DeadTelegram(FakeTelegram):
    def send_message(
        self,
        text: str,
        buttons: list[tuple[str, str]] | None = None,
        reply_to: int | None = None,
    ) -> int:
        raise OSError("offline")


def morning_llm() -> FakeLLM:
    return FakeLLM({"content": [_morning()], "guardrail_judge": [_verdict()]})


def posts(db: Session) -> list[Post]:
    db.expire_all()
    return list(db.scalars(select(Post).order_by(Post.day, Post.slot)))


def texts(bot: FakeTelegram) -> list[str]:
    return [s["text"] for s in bot.sent if s["method"] == "send_message"]


def alerts(db: Session) -> list[str]:
    return [a.message for a in db.scalars(select(Alert))]


def test_0800_drafts_morning_and_sends_for_review(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    bot, calls = FakeTelegram(), Calls()
    tick(make_deps(db_factory, dirs, morning_llm(), bot, calls), local(D, 8, 0))

    [post] = posts(db)
    assert (post.slot, post.status, post.revision) == ("morning", "pending", 1)
    assert post.title == _morning().title
    assert post.source_text == ARTICLE.text and post.research_url == ARTICLE.url
    assert post.image_paths == [str((dirs / "data" / "media" / "m.jpg").resolve())]
    assert Path(post.image_paths[0]).is_absolute()
    assert post.image_note == "Ảnh: Jane / Unsplash"
    item = db.scalar(select(ResearchItem).where(ResearchItem.url == ARTICLE.url))
    assert item is not None and item.used_post_id == post.id
    assert [s["method"] for s in bot.sent] == ["send_photos", "send_message"]
    sent = bot.sent[-1]
    assert sent["buttons"][0] == ("✅ Đăng", f"ok:{post.id}:1")
    assert post.telegram_message_id == sent["message_id"]


def test_morning_review_gets_article_text_as_source(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    llm = morning_llm()
    tick(make_deps(db_factory, dirs, llm, FakeTelegram(), Calls()), local(D, 8, 0))
    judge = next(c for c in llm.calls if c.get("agent") == "guardrail_judge")
    assert ARTICLE.text[:200] in judge["user"]


def test_late_start_1040_drafts_morning_and_publishes_after_approval_immediately(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    bot = FakeTelegram()
    deps = make_deps(db_factory, dirs, morning_llm(), bot, Calls())
    tick(deps, local(D, 10, 40))
    [post] = posts(db)
    assert post.status == "pending"

    assert store.approve(db, post.id, post.revision, local(D, 10, 45)) == "ok"
    tick(deps, local(D, 10, 46))
    [post] = posts(db)
    assert post.status == "published" and post.fb_post_id == "DRY_RUN"
    assert "🧪 (Chạy thử) Đã giả lập đăng bài sáng." in texts(bot)


def test_start_after_noon_skips_morning_draft(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    calls = Calls()
    tick(make_deps(db_factory, dirs, morning_llm(), FakeTelegram(), calls), local(D, 12, 5))
    assert posts(db) == []
    assert calls.research == 0


def test_restart_does_not_redraft_or_republish(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    bot, calls = FakeTelegram(), Calls()
    deps = make_deps(db_factory, dirs, morning_llm(), bot, calls)
    tick(deps, local(D, 8, 0))
    tick(deps, local(D, 8, 1))
    [post] = posts(db)
    store.approve(db, post.id, post.revision, local(D, 8, 30))

    tick(deps, local(D, 9, 0))
    tick(deps, local(D, 9, 1))
    startup(deps, local(D, 9, 2))

    assert db.scalar(select(func.count()).select_from(Post)) == 1
    assert posts(db)[0].status == "published"
    assert calls.research == 1
    assert texts(bot).count("🧪 (Chạy thử) Đã giả lập đăng bài sáng.") == 1


def test_1500_drafts_afternoon_with_pictures(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    folder = dirs / "Picture" / "Hầm A"
    folder.mkdir()
    (folder / "a.jpg").write_bytes(b"x")
    (folder / "b.png").write_bytes(b"x")
    bot, calls = FakeTelegram(), Calls()
    llm = FakeLLM({"content": [_draft()], "guardrail_judge": [_verdict()]})
    tick(make_deps(db_factory, dirs, llm, bot, calls), local(D, 15, 0))

    [post] = posts(db)
    assert (post.slot, post.status) == ("afternoon", "pending")
    root = (dirs / "Picture").resolve()
    assert post.image_paths == [str(root / "Hầm A/a.jpg"), str(root / "Hầm A/b.png")]
    assert post.picture_folder == "Hầm A"
    assert post.image_note is None and post.source_text is None
    assert calls.research == 0 and calls.images == 0
    assert bot.sent[0] == {"method": "send_photos", "paths": post.image_paths}
    assert post.telegram_message_id == bot.sent[-1]["message_id"]


def test_afternoon_without_pictures_warns(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    bot = FakeTelegram()
    llm = FakeLLM({"content": [_draft()], "guardrail_judge": [_verdict()]})
    tick(make_deps(db_factory, dirs, llm, bot, Calls()), local(D, 16, 0))
    [post] = posts(db)
    assert post.status == "pending" and post.image_paths == []
    assert post.image_note == "⚠️ Thư mục Picture không có ảnh dùng được."
    assert "⚠️ Thư mục Picture không có ảnh dùng được." in texts(bot)[-1]


def test_2000_expires_unapproved_and_notifies(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    post = store.claim_slot(db, D, "morning")
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)
    post.telegram_message_id = 50
    db.commit()
    bot, calls = FakeTelegram(), Calls()
    tick(make_deps(db_factory, dirs, None, bot, calls), local(D, 20, 0))

    assert posts(db)[0].status == "expired"
    assert {"method": "edit_buttons_removed", "message_id": 50} in bot.sent
    assert texts(bot) == ["⏰ Bài sáng 13/10 chưa được duyệt trước 20:00 nên đã bỏ."]
    assert len(posts(db)) == 1  # no afternoon draft at 20:00


def test_yesterdays_approved_post_expires_instead_of_publishing(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    yesterday = D - timedelta(days=1)
    post = store.claim_slot(db, yesterday, "afternoon")
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)
    # Approved in time, but the PC stayed off until the next day.
    assert store.approve(db, post.id, 1, local(yesterday, 16, 0)) == "ok"
    bot = FakeTelegram()
    tick(make_deps(db_factory, dirs, None, bot, Calls()), local(D, 12, 30))

    [post] = posts(db)
    assert post.status == "expired" and post.fb_post_id is None
    assert not any("Đã giả lập đăng" in t for t in texts(bot))


def test_no_article_found_notifies_and_marks_failed(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    bot, calls = FakeTelegram(), Calls()
    llm = FakeLLM({"content": [_morning(article_url="")]})
    deps = make_deps(db_factory, dirs, llm, bot, calls)
    tick(deps, local(D, 8, 0))

    [post] = posts(db)
    assert post.status == "failed" and post.error == "Không tìm được tin phù hợp"
    assert texts(bot) == ["Sáng nay không tìm được tin phù hợp nên không có bài sáng."]
    assert calls.images == 0
    tick(deps, local(D, 8, 1))  # not retried
    assert calls.research == 1


def test_no_research_results_skips_writer(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    bot = FakeTelegram()
    llm = FakeLLM({})
    tick(make_deps(db_factory, dirs, llm, bot, Calls(), articles=[]), local(D, 8, 0))
    [post] = posts(db)
    assert post.status == "failed" and post.error == "Không tìm được tin phù hợp"
    assert llm.calls == []
    assert texts(bot) == ["Sáng nay không tìm được tin phù hợp nên không có bài sáng."]


def test_network_failure_at_0800_retries_after_10_minutes(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    calls, bot = Calls(), FakeTelegram()
    calls.fail_research = 1
    deps = make_deps(db_factory, dirs, morning_llm(), bot, calls)

    tick(deps, local(D, 8, 0))
    assert posts(db) == []  # slot freed, no failed row
    assert alerts(db) == []

    tick(deps, local(D, 8, 5))
    assert calls.research == 1  # too soon to retry

    tick(deps, local(D, 8, 11))
    assert calls.research == 2
    [post] = posts(db)
    assert post.status == "pending" and post.telegram_message_id is not None
    assert alerts(db) == []


def test_three_draft_failures_give_one_failed_row_and_one_alert(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    calls = Calls()
    calls.fail_research = 5
    deps = make_deps(db_factory, dirs, morning_llm(), FakeTelegram(), calls)
    for minute in (0, 10, 20, 30, 40):
        tick(deps, local(D, 8, minute))
    assert calls.research == 3
    [post] = posts(db)
    assert post.status == "failed" and post.error == "Soạn bài thất bại"
    assert alerts(db) == ["Không soạn được bài sáng hôm nay (lỗi khi tìm tin/viết bài)."]
    tick(deps, local(D, 20, 0))  # failed row exists: no "lost slot" alert on top
    assert len(alerts(db)) == 1


def test_missing_llm_is_retried_then_fails_with_one_alert(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    deps = make_deps(db_factory, dirs, None, FakeTelegram(), Calls())
    tick(deps, local(D, 8, 0))
    assert posts(db) == [] and alerts(db) == []
    tick(deps, local(D, 8, 10))
    tick(deps, local(D, 8, 20))
    [post] = posts(db)
    assert post.status == "failed" and post.error == "Chưa cấu hình AI"
    assert alerts(db) == ["Không soạn được bài sáng: chưa cấu hình AI."]


def test_window_closes_after_failures_alerts_once_at_day_end(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    calls = Calls()
    calls.fail_research = 1
    deps = make_deps(db_factory, dirs, morning_llm(), FakeTelegram(), calls)
    tick(deps, local(D, 11, 55))  # one failure, then the morning window closes
    tick(deps, local(D, 12, 10))
    assert posts(db) == [] and alerts(db) == []

    tick(deps, local(D, 20, 0))
    tick(deps, local(D, 20, 1))
    assert alerts(db) == ["Hôm nay không soạn được bài sáng (lỗi kết nối/AI)."]
    row = db.scalar(select(Setting).where(Setting.key == "DRAFT_RETRY:2026-10-13:morning"))
    assert row is not None and row.value.startswith("1|") and row.value.endswith("|notified")


def test_startup_deletes_orphaned_drafting_row_while_window_open(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    orphan = store.claim_slot(db, D, "morning")  # PC switched off mid-draft
    assert orphan is not None
    orphan_id = orphan.id
    calls = Calls()
    startup(make_deps(db_factory, dirs, morning_llm(), FakeTelegram(), calls), local(D, 9, 30))
    [post] = posts(db)
    assert post.status == "pending" and post.id != orphan_id
    assert calls.research == 1
    assert alerts(db) == []


def test_startup_fails_orphaned_drafting_row_after_window(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    assert store.claim_slot(db, D, "morning") is not None
    calls = Calls()
    startup(make_deps(db_factory, dirs, morning_llm(), FakeTelegram(), calls), local(D, 13, 0))
    [post] = posts(db)
    assert post.status == "failed" and post.error == "Bị gián đoạn khi đang soạn"
    assert calls.research == 0
    assert alerts(db) == [
        "Bài sáng 13/10 bị gián đoạn khi đang soạn (máy tắt) nên không có bài."
    ]


def test_context_failure_does_not_leave_drafting_row(
    db: Session, db_factory: SessionFactory, dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: Any) -> Any:
        raise FileNotFoundError("kb missing")

    monkeypatch.setattr(scheduler, "load_knowledge", broken)
    tick(make_deps(db_factory, dirs, morning_llm(), FakeTelegram(), Calls()), local(D, 8, 0))
    assert [p.status for p in posts(db)] == ["failed"]


def test_unsent_pending_post_is_resent_on_next_tick(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    post = store.claim_slot(db, D, "morning")
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)  # never reached Telegram
    bot = FakeTelegram()
    deps = make_deps(db_factory, dirs, None, bot, Calls())
    tick(deps, local(D, 8, 30))
    [post] = posts(db)
    sent = [s for s in bot.sent if s["method"] == "send_message"]
    assert len(sent) == 1 and post.telegram_message_id == sent[0]["message_id"]
    tick(deps, local(D, 8, 31))
    assert len([s for s in bot.sent if s["method"] == "send_message"]) == 1


def test_resend_failure_does_not_alert_every_tick(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    post = store.claim_slot(db, D, "morning")
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)
    deps = make_deps(db_factory, dirs, None, DeadTelegram(), Calls())
    tick(deps, local(D, 8, 30))
    tick(deps, local(D, 8, 31))
    assert alerts(db) == []
    assert posts(db)[0].telegram_message_id is None


def test_unsent_post_expiry_says_it_never_reached_telegram(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    post = store.claim_slot(db, D, "afternoon")
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)
    bot = FakeTelegram()
    tick(make_deps(db_factory, dirs, None, bot, Calls()), local(D, 20, 0))
    assert posts(db)[0].status == "expired"
    assert texts(bot) == ["⏰ Bài chiều 13/10 chưa gửi được lên Telegram nên đã bỏ."]
    assert not any(s["method"] == "edit_buttons_removed" for s in bot.sent)


def test_approved_post_expiry_says_pc_was_off(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    post = store.claim_slot(db, D, "morning")
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)
    post.telegram_message_id = 50
    db.commit()
    store.approve(db, post.id, 1, local(D, 8, 30))
    bot = FakeTelegram()
    # PC was off from before 09:00 until after 20:00.
    tick(make_deps(db_factory, dirs, None, bot, Calls()), local(D, 20, 30))
    [post] = posts(db)
    assert post.status == "expired" and post.fb_post_id is None
    assert texts(bot) == [
        "⏰ Bài sáng 13/10 đã được duyệt nhưng không đăng được trong ngày "
        "(máy tắt hoặc mất mạng), đã bỏ."
    ]


def test_one_step_failure_does_not_block_publishing(
    db: Session, db_factory: SessionFactory, dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    post = store.claim_slot(db, D, "afternoon")
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)
    store.approve(db, post.id, 1, local(D, 15, 30))

    def boom(*_a: Any) -> None:
        raise RuntimeError("draft exploded")

    monkeypatch.setattr(scheduler, "draft_afternoon", boom)
    bot = FakeTelegram()
    tick(make_deps(db_factory, dirs, None, bot, Calls()), local(D, 16, 30))

    assert posts(db)[0].status == "published"
    assert "🧪 (Chạy thử) Đã giả lập đăng bài chiều." in texts(bot)
    assert any("RuntimeError" in m for m in alerts(db))


def test_review_send_failure_keeps_post_pending_and_alerts(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    tick(make_deps(db_factory, dirs, morning_llm(), DeadTelegram(), Calls()), local(D, 8, 0))
    [post] = posts(db)
    assert post.status == "pending" and post.telegram_message_id is None
    assert "Không gửi được bài sáng lên Telegram." in alerts(db)


def test_startup_recovers_stuck_then_ticks(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    post = store.claim_slot(db, D, "morning")
    assert post is not None
    post.status = "publishing"
    db.commit()
    calls = Calls()
    startup(make_deps(db_factory, dirs, morning_llm(), FakeTelegram(), calls), local(D, 9, 0))
    [post] = posts(db)
    assert post.status == "failed"
    assert calls.research == 0  # slot already claimed


# --- final review fixes ------------------------------------------------------------


def _approved(db: Session, day: date, slot: Slot = "morning") -> Post:
    post = store.claim_slot(db, day, slot)
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)
    post.telegram_message_id = 50
    post.status, post.approved_at = "approved", local(day, 8, 30)
    db.commit()
    return post


def test_failed_expiry_still_never_publishes_yesterdays_approved_post(
    db: Session, db_factory: SessionFactory, dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _approved(db, D - timedelta(days=1))

    def locked(*_a: Any) -> Any:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(scheduler, "expire_open", locked)
    bot = FakeTelegram()
    tick(make_deps(db_factory, dirs, None, bot, Calls()), local(D, 12, 30))
    [post] = posts(db)
    assert post.status == "approved" and post.fb_post_id is None
    assert not any("Đã giả lập đăng" in t for t in texts(bot))


def test_approval_after_expire_race_is_not_published(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    post = store.claim_slot(db, D, "afternoon")
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, False)
    post.telegram_message_id = 50
    db.commit()
    bot = FakeTelegram()
    deps = make_deps(db_factory, dirs, None, bot, Calls())
    tick(deps, local(D, 20, 0))  # expires and tells the director it was dropped
    # The Telegram thread had read the post as pending at 19:59:59.
    assert store.approve(db, post.id, 1, local(D, 19, 59) + timedelta(seconds=59)) == "stale"
    tick(deps, local(D, 20, 0) + timedelta(seconds=30))
    [post] = posts(db)
    assert post.status == "expired" and post.fb_post_id is None
    assert not any("Đã giả lập đăng" in t for t in texts(bot))


def _live_deps(db_factory: SessionFactory, tmp: Path, bot: FakeTelegram) -> Deps:
    deps = make_deps(db_factory, tmp, None, bot, Calls())
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        PICTURE_DIR=str(tmp / "Picture"),
        DATA_DIR=str(tmp / "data"),
        DRY_RUN=False,
        META_PAGE_ID="123",
        META_PAGE_ACCESS_TOKEN="SECRET",
        META_GRAPH_VERSION="v26.0",
    )
    deps.settings = settings
    deps.graph = GraphClient(settings)
    return deps


FEED = "https://graph.facebook.com/v26.0/123/feed"
COMMENTS = "https://graph.facebook.com/v26.0/123_9/comments"


def test_connect_error_keeps_post_approved_and_next_tick_publishes(
    db: Session, db_factory: SessionFactory, dirs: Path, respx_mock: Any
) -> None:
    _approved(db, D)
    feed = respx_mock.post(FEED).mock(
        side_effect=[httpx.ConnectError("offline"), httpx.Response(200, json={"id": "123_9"})]
    )
    respx_mock.post(COMMENTS).respond(200, json={"id": "c1"})
    bot = FakeTelegram()
    deps = _live_deps(db_factory, dirs, bot)

    tick(deps, local(D, 9, 0))
    [post] = posts(db)
    assert post.status == "approved" and post.fb_post_id is None
    assert alerts(db) == [] and texts(bot) == []

    tick(deps, local(D, 9, 1))
    [post] = posts(db)
    assert post.status == "published" and post.fb_post_id == "123_9"
    assert feed.call_count == 2
    assert texts(bot) == ["✅ Đã đăng bài sáng."]


def test_connect_error_until_day_end_expires_with_clear_text(
    db: Session, db_factory: SessionFactory, dirs: Path, respx_mock: Any
) -> None:
    _approved(db, D)
    feed = respx_mock.post(FEED).mock(side_effect=httpx.ConnectTimeout("offline"))
    bot = FakeTelegram()
    deps = _live_deps(db_factory, dirs, bot)
    tick(deps, local(D, 19, 59))
    tick(deps, local(D, 20, 0))
    tick(deps, local(D, 20, 1))
    [post] = posts(db)
    assert post.status == "expired" and feed.call_count == 1
    assert texts(bot) == [
        "⏰ Bài sáng 13/10 đã được duyệt nhưng không đăng được trong ngày "
        "(máy tắt hoặc mất mạng), đã bỏ."
    ]


def test_read_timeout_fails_with_urgent_alert_and_no_retry(
    db: Session, db_factory: SessionFactory, dirs: Path, respx_mock: Any
) -> None:
    _approved(db, D)
    feed = respx_mock.post(FEED).mock(side_effect=httpx.ReadTimeout("slow"))
    deps = _live_deps(db_factory, dirs, FakeTelegram())
    tick(deps, local(D, 9, 0))
    tick(deps, local(D, 9, 1))
    [post] = posts(db)
    assert post.status == "failed" and feed.call_count == 1
    [alert] = db.scalars(select(Alert)).all()
    assert alert.level == "urgent" and "không rõ đã đăng" in alert.message


class FlakyText(FakeTelegram):
    def __init__(self, fail_texts: int = 0) -> None:
        super().__init__()
        self.fail_texts = fail_texts

    def send_message(
        self,
        text: str,
        buttons: list[tuple[str, str]] | None = None,
        reply_to: int | None = None,
    ) -> int:
        if self.fail_texts > 0:
            self.fail_texts -= 1
            raise OSError("offline")
        return super().send_message(text, buttons, reply_to)


def test_resend_sends_text_only_never_photos(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    post = store.claim_slot(db, D, "afternoon")
    assert post is not None
    post.image_paths = [str(dirs / "Picture" / "a.jpg")]
    store.save_draft(db, post, draft(), REPORT, False)  # never reached Telegram
    bot = FlakyText(fail_texts=5)
    deps = make_deps(db_factory, dirs, None, bot, Calls())
    for minute in range(30, 37):
        tick(deps, local(D, 14, minute))
    assert not any(s["method"] == "send_photos" for s in bot.sent)
    [sent] = [s for s in bot.sent if s["method"] == "send_message"]
    assert sent["buttons"] == [
        ("✅ Đăng", f"ok:{post.id}:1"),
        ("❌ Không đăng", f"no:{post.id}:1"),
    ]
    assert posts(db)[0].telegram_message_id == sent["message_id"]


def test_tick_redelivers_undelivered_alert(
    db: Session,
    db_factory: SessionFactory,
    dirs: Path,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock: Any,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    get_settings.cache_clear()
    now = local(D, 9, 0)
    db.add(
        Alert(
            level="urgent",
            channel="telegram",
            message="kiểm tra Fanpage",
            created_at=now - timedelta(minutes=10),
            last_attempt_at=now - timedelta(minutes=10),
        )
    )
    db.commit()
    route = respx_mock.post(url__regex=r"https://api\.telegram\.org/bottok123/sendMessage")
    route.respond(200, json={"ok": True, "result": {"message_id": 1}})
    tick(make_deps(db_factory, dirs, None, FakeTelegram(), Calls()), now)
    db.expire_all()
    [alert] = db.scalars(select(Alert)).all()
    assert alert.delivered_at is not None and route.call_count == 1


def test_morning_post_approved_at_0815_is_published_at_once(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    bot = FakeTelegram()
    deps = make_deps(db_factory, dirs, morning_llm(), bot, Calls())
    tick(deps, local(D, 8, 0))
    [post] = posts(db)
    assert store.approve(db, post.id, post.revision, local(D, 8, 15)) == "ok"
    tick(deps, local(D, 8, 15))  # well before the old 09:00 slot time
    [post] = posts(db)
    assert post.status == "published"


def test_morning_research_is_limited_to_news_domains(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    seen: dict[str, Any] = {}

    def research(
        llm: Any, db: Session, queries: list[str], job_id: Any, **kw: Any
    ) -> list[Article]:
        seen.update(kw)
        return []

    deps = make_deps(db_factory, dirs, morning_llm(), FakeTelegram(), Calls())
    deps.research_fn = research
    tick(deps, local(D, 8, 0))
    assert "vnexpress.net" in seen["domains"]


def test_morning_research_asks_for_news_from_the_last_90_days(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    seen: dict[str, Any] = {}

    def research(
        llm: Any, db: Session, queries: list[str], job_id: Any, **kw: Any
    ) -> list[Article]:
        seen.update(kw)
        return []

    deps = make_deps(db_factory, dirs, morning_llm(), FakeTelegram(), Calls())
    deps.research_fn = research
    tick(deps, local(D, 8, 0))
    assert seen["max_age_days"] == 90
