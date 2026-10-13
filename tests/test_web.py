from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import orm

from app.config import Settings
from app.db.models import Post
from app.web.app import create_app

NOW = datetime(2026, 10, 13, 3, 0, tzinfo=UTC)  # 10:00 local, a Tuesday
DAY = date(2026, 10, 13)


def _settings(tmp_path: Path, **kw: object) -> Settings:
    kw.setdefault("PICTURE_DIR", str(tmp_path / "Picture"))
    kw.setdefault("DATA_DIR", str(tmp_path / "data"))
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def _client(db_factory: Callable[[], orm.Session], settings: Settings) -> TestClient:
    return TestClient(create_app(db_factory, settings, now_fn=lambda: NOW))


def test_today_shows_both_slots_before_drafting(
    db_factory: Callable[[], orm.Session], tmp_path: Path
) -> None:
    html = _client(db_factory, _settings(tmp_path)).get("/").text
    assert 'http-equiv="refresh" content="60"' in html
    assert "Thứ Ba 13/10/2026" in html
    assert "Bài sáng" in html and "Bài chiều" in html
    assert html.count("Chưa đến giờ soạn") == 2
    assert html.index("Bài sáng") < html.index("Bài chiều")
    assert "Sẽ có ở đợt 2 (sau khi Meta duyệt quyền nhắn tin)." in html
    assert "Chạy thử" in html  # DRY_RUN defaults to true


def test_today_shows_published_with_comment_badge(
    db_factory: Callable[[], orm.Session], tmp_path: Path
) -> None:
    with db_factory() as db:
        db.add(
            Post(
                day=DAY,
                slot="morning",
                status="published",
                title="Tiêu đề <script>x</script>",
                body="a" * 400,
                comment_id="c1",
                fb_post_id="p1",
                image_paths=["/x/y.jpg"],
                image_note="Ảnh minh họa",
            )
        )
        db.add(Post(day=DAY, slot="afternoon", status="failed", error="Lỗi mạng"))
        db.commit()
        pid = db.query(Post).filter_by(slot="morning").one().id
    html = _client(db_factory, _settings(tmp_path, DRY_RUN=False)).get("/").text
    assert "Đã đăng ✓" in html
    assert "Bình luận giới thiệu đã gắn ✓" in html
    assert "Lỗi: Lỗi mạng" in html
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
    assert "a" * 300 in html and "a" * 301 not in html
    assert f'src="/media/{pid}/0"' in html
    assert "Ảnh minh họa" in html
    assert "Chạy thử" not in html


def test_media_serves_allowed_and_rejects_outside(
    db_factory: Callable[[], orm.Session], tmp_path: Path
) -> None:
    pics = tmp_path / "Picture"
    pics.mkdir()
    ok = pics / "a.jpg"
    ok.write_bytes(b"img")
    secret = tmp_path / ".env"
    secret.write_text("SECRET")
    with db_factory() as db:
        post = Post(
            day=DAY,
            slot="morning",
            image_paths=[str(ok), "../../.env", str(secret), "a.jpg", str(pics / "none.jpg")],
        )
        db.add(post)
        db.commit()
        pid = post.id
    client = _client(db_factory, _settings(tmp_path))
    assert client.get(f"/media/{pid}/0").content == b"img"
    assert client.get(f"/media/{pid}/3").content == b"img"  # relative -> PICTURE_DIR
    for i in (1, 2, 4, 9):
        assert client.get(f"/media/{pid}/{i}").status_code == 404
    assert client.get("/media/00000000-0000-0000-0000-000000000000/0").status_code == 404


def test_page_contains_no_secrets(db_factory: Callable[[], orm.Session], tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        TELEGRAM_BOT_TOKEN="tg-secret-111",
        META_PAGE_ACCESS_TOKEN="meta-secret-222",
        ANTHROPIC_API_KEY="anthropic-secret-333",
        META_APP_SECRET="app-secret-444",
    )
    resp = _client(db_factory, settings).get("/")
    for secret in ("tg-secret", "meta-secret", "anthropic-secret", "app-secret"):
        assert secret not in resp.text


def test_health(db_factory: Callable[[], orm.Session], tmp_path: Path) -> None:
    resp = _client(db_factory, _settings(tmp_path)).get("/health")
    assert resp.json() == {"ok": True}
