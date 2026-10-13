from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import scheduler
from app.config import Settings, get_settings
from app.content.images import ImagePlan, ImageResult
from app.content.research import Article
from app.db.models import Alert, Post, ResearchItem
from app.llm.client import FakeLLM
from app.posts import store
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


def make_deps(
    db_factory: SessionFactory,
    tmp: Path,
    llm: FakeLLM | None,
    bot: FakeTelegram,
    calls: Calls,
    articles: list[Article] | None = None,
    research_error: Exception | None = None,
) -> Deps:
    found = [ARTICLE] if articles is None else articles

    def research(
        llm: Any, db: Session, queries: list[str], job_id: Any, **kw: Any
    ) -> list[Article]:
        calls.research += 1
        if research_error is not None:
            raise research_error
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
        return ImageResult(paths=[str((dest_dir / "m.jpg").resolve())], note="Ảnh kho Pexels")

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
    assert post.image_note == "Ảnh kho Pexels"
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
    # Approved via an old button, after the day ended but before any tick ran.
    assert store.approve(db, post.id, 1, local(yesterday, 21, 0)) == "ok"
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


def test_missing_llm_marks_failed_and_alerts(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    tick(make_deps(db_factory, dirs, None, FakeTelegram(), Calls()), local(D, 8, 0))
    [post] = posts(db)
    assert post.status == "failed" and post.error
    assert any("bài sáng" in m for m in alerts(db))


def test_job_failure_marks_failed_and_alerts(
    db: Session, db_factory: SessionFactory, dirs: Path
) -> None:
    deps = make_deps(
        db_factory, dirs, morning_llm(), FakeTelegram(), Calls(), research_error=OSError("net")
    )
    tick(deps, local(D, 8, 0))
    [post] = posts(db)
    assert post.status == "failed" and post.error
    assert any("Không soạn được bài sáng" in m for m in alerts(db))


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
    class DeadTelegram(FakeTelegram):
        def send_message(
            self,
            text: str,
            buttons: list[tuple[str, str]] | None = None,
            reply_to: int | None = None,
        ) -> int:
            raise OSError("offline")

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
