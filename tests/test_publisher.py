from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import orm

from app.config import Settings, get_settings
from app.db.models import Alert, PictureUse, Post
from app.meta.graph import GraphClient, GraphError
from app.posts.publisher import (
    COMMENT_TEXT,
    compose_message,
    publish_post,
    recover_stuck,
    retry_missing_comments,
)
from app.posts.store import due_for_publish
from app.telegram.bot import FakeTelegram, TelegramError

NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
DAY = date(2026, 10, 13)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    pictures = tmp_path / "Picture"
    pictures.mkdir()
    monkeypatch.setenv("PICTURE_DIR", str(pictures))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_settings.cache_clear()
    yield pictures
    get_settings.cache_clear()


class FakeGraph(GraphClient):
    def __init__(self) -> None:
        super().__init__(Settings(META_PAGE_ID="1", META_PAGE_ACCESS_TOKEN="t"))
        self.published: list[tuple[str, list[str]]] = []
        self.comments: list[tuple[str, str]] = []
        self.publish_error: GraphError | None = None
        self.comment_error: GraphError | None = None
        self.on_publish = lambda: None

    def publish(self, message: str, image_paths: list[str]) -> str:
        self.on_publish()
        if self.publish_error:
            raise self.publish_error
        self.published.append((message, image_paths))
        return "1_100"

    def comment(self, post_id: str, text: str) -> str:
        if self.comment_error:
            raise self.comment_error
        self.comments.append((post_id, text))
        return "c_1"


def make_post(
    db: orm.Session,
    slot: str = "afternoon",
    images: list[str] | None = None,
    day: date = DAY,
) -> Post:
    post = Post(
        day=day,
        slot=slot,
        status="approved",
        title="Tiêu đề",
        body="Nội dung",
        cta="Liên hệ ngay",
        hashtags=["#Bestone", "chongtham"],
        sources=[{"name": "VnExpress", "url": "https://vnexpress.net/x"}],
        image_paths=images or [],
    )
    db.add(post)
    db.commit()
    return post


def test_compose_message(db: orm.Session) -> None:
    morning = make_post(db, "morning")
    assert compose_message(morning) == (
        "Tiêu đề\n\nNội dung\n\nLiên hệ ngay\n\n#Bestone #chongtham\n\n"
        "Nguồn: VnExpress – https://vnexpress.net/x"
    )
    morning.slot = "afternoon"
    assert "Nguồn" not in compose_message(morning)


def test_publish_post_marks_publishing_before_call(db: orm.Session) -> None:
    post = make_post(db)
    graph = FakeGraph()
    seen: list[str] = []
    graph.on_publish = lambda: seen.append(db.get(Post, post.id).status)  # type: ignore[union-attr]
    publish_post(db, graph, FakeTelegram(), post, NOW, dry_run=False)
    assert seen == ["publishing"]
    assert post.status == "published"


def test_publish_post_adds_comment_and_records_picture_use(db: orm.Session, env: Path) -> None:
    img = env / "Du an A" / "1.jpg"
    img.parent.mkdir()
    img.write_bytes(b"x")
    outside = env.parent / "other.jpg"
    outside.write_bytes(b"x")
    post = make_post(db, images=[str(img), str(outside)])
    graph, bot = FakeGraph(), FakeTelegram()
    publish_post(db, graph, bot, post, NOW, dry_run=False)
    assert post.fb_post_id == "1_100" and post.comment_id == "c_1"
    assert post.published_at is not None and post.status == "published"
    assert graph.comments == [("1_100", COMMENT_TEXT)]
    uses = {u.path: u.used_count for u in db.query(PictureUse).all()}
    assert uses == {"Du an A/1.jpg": 1}
    assert bot.sent[-1]["text"] == "✅ Đã đăng bài chiều."


def test_morning_does_not_record_picture_use(db: orm.Session, env: Path) -> None:
    img = env / "1.jpg"
    img.write_bytes(b"x")
    post = make_post(db, "morning", images=[str(img)])
    publish_post(db, FakeGraph(), FakeTelegram(), post, NOW, dry_run=False)
    assert db.query(PictureUse).count() == 0


def test_token_expired_sends_urgent_alert(db: orm.Session) -> None:
    post = make_post(db)
    graph = FakeGraph()
    graph.publish_error = GraphError(190, "expired")
    publish_post(db, graph, FakeTelegram(), post, NOW, dry_run=False)
    assert post.status == "failed" and post.error == "expired"
    alert = db.query(Alert).one()
    assert alert.level == "urgent"
    assert alert.message == (
        "Token Facebook hết hạn hoặc bị thu hồi. Cần lấy token mới (xem hướng dẫn)."
    )


def test_other_graph_error_warns(db: orm.Session) -> None:
    post = make_post(db, "morning")
    graph = FakeGraph()
    graph.publish_error = GraphError(100, "bad param")
    publish_post(db, graph, FakeTelegram(), post, NOW, dry_run=False)
    alert = db.query(Alert).one()
    assert alert.level == "warn" and alert.message == "Đăng bài sáng thất bại: bad param"


def test_no_graph_and_not_dry_run_fails(db: orm.Session) -> None:
    post = make_post(db)
    publish_post(db, None, FakeTelegram(), post, NOW, dry_run=False)
    assert post.status == "failed" and post.error == "Chưa cấu hình Facebook"
    assert db.query(Alert).one().level == "warn"


def test_dry_run_makes_no_graph_calls(db: orm.Session, env: Path) -> None:
    img = env / "1.jpg"
    img.write_bytes(b"x")
    post = make_post(db, images=[str(img)])
    graph = FakeGraph()
    bot = FakeTelegram()
    publish_post(db, graph, bot, post, NOW, dry_run=True)
    assert not graph.published and not graph.comments
    assert post.status == "published"
    assert post.fb_post_id == "DRY_RUN" and post.comment_id == "DRY_RUN"
    assert bot.sent[-1]["text"] == "🧪 (Chạy thử) Đã giả lập đăng bài chiều."
    assert db.query(PictureUse).one().path == "1.jpg"


def test_dry_run_works_without_graph(db: orm.Session) -> None:
    post = make_post(db, "morning")
    publish_post(db, None, FakeTelegram(), post, NOW, dry_run=True)
    assert post.status == "published" and post.fb_post_id == "DRY_RUN"


def test_recover_stuck_never_republishes(db: orm.Session) -> None:
    post = make_post(db, "morning")
    post.status = "publishing"
    db.commit()
    recover_stuck(db, FakeTelegram())
    assert post.status == "failed" and post.error == "Bị gián đoạn khi đang đăng"
    alert = db.query(Alert).one()
    assert alert.level == "urgent"
    assert alert.message.startswith("Bài sáng 13/10 bị gián đoạn lúc đang đăng.")
    assert "KHÔNG tự đăng lại" in alert.message
    assert due_for_publish(db, NOW) == []


def test_comment_failure_is_retried_later(db: orm.Session) -> None:
    post = make_post(db)
    graph = FakeGraph()
    graph.comment_error = GraphError(-1, "net")
    publish_post(db, graph, FakeTelegram(), post, NOW, dry_run=False)
    assert post.status == "published" and post.comment_id is None
    graph.comment_error = None
    retry_missing_comments(db, graph, NOW)
    assert post.comment_id == "c_1"
    assert graph.comments == [("1_100", COMMENT_TEXT)]
    retry_missing_comments(db, graph, NOW)
    assert len(graph.comments) == 1


def test_retry_skips_dry_run_other_days_and_no_graph(db: orm.Session) -> None:
    dry = make_post(db)
    dry.status, dry.fb_post_id = "published", "DRY_RUN"
    old = make_post(db, "morning", day=date(2026, 10, 12))
    old.status, old.fb_post_id = "published", "1_5"
    db.commit()
    graph = FakeGraph()
    retry_missing_comments(db, graph, NOW)
    assert graph.comments == []
    dry.fb_post_id = "1_6"
    db.commit()
    retry_missing_comments(db, None, NOW)
    assert graph.comments == []


@pytest.mark.parametrize("exc", [TelegramError("down"), httpx.ConnectError("x")])
def test_telegram_failure_does_not_undo_publish(db: orm.Session, exc: Exception) -> None:
    class Broken(FakeTelegram):
        def send_message(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise exc

    post = make_post(db)
    publish_post(db, FakeGraph(), Broken(), post, NOW, dry_run=False)
    assert post.status == "published" and post.fb_post_id == "1_100"
