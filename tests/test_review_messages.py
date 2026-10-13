from datetime import date
from typing import Any

from app.db.models import Post
from app.telegram.bot import FakeTelegram
from app.telegram.review import format_review, send_for_review


def _post(**kw: Any) -> Post:
    base: dict[str, Any] = dict(
        id=7,
        day=date(2026, 10, 13),
        slot="morning",
        revision=2,
        title="Tiêu đề",
        body="Nội dung bài.",
        hashtags=["#a", "#b"],
        cta="Liên hệ ngay",
        sources=[{"name": "Báo X", "url": "http://x.vn/1"}],
        image_paths=[],
        image_note=None,
        guardrail_report=None,
        blocking=False,
    )
    base.update(kw)
    return Post(**base)


def test_format_review_layout() -> None:
    text = format_review(_post())
    assert text.startswith("📝 BÀI SÁNG 13/10 — đăng lúc 09:00 (bản 2)\n\nTiêu đề\n\nNội dung bài.")
    assert "\n\nLiên hệ ngay\n#a #b\n\nNguồn: Báo X – http://x.vn/1" in text
    assert text.endswith("💬 Muốn sửa: trả lời (reply) tin nhắn này và gõ góp ý.")
    assert "⚠️" not in text and "⛔" not in text


def test_format_review_afternoon_and_optional_lines() -> None:
    text = format_review(
        _post(
            slot="afternoon",
            sources=[],
            image_note="Ảnh minh họa AI",
            guardrail_report={"flags": ["f1", "f2"]},
        )
    )
    assert "BÀI CHIỀU" in text and "16:30" in text
    assert "Nguồn:" not in text
    assert "Ảnh minh họa AI" in text
    assert "⚠️ Cần xem: f1; f2" in text


def test_format_review_blocking_has_warning_and_single_button() -> None:
    post = _post(blocking=True)
    assert "⛔ Bài có lỗi thông tin nên chưa thể đăng. Hãy góp ý để AI sửa." in format_review(post)
    bot = FakeTelegram()
    mid = send_for_review(bot, post)
    assert mid == 100
    assert bot.sent[-1]["buttons"] == [("❌ Không đăng", "no:7:2")]


def test_send_for_review_normal_buttons_and_photos() -> None:
    bot = FakeTelegram()
    send_for_review(bot, _post(image_paths=["/a.jpg"]))
    assert [s["method"] for s in bot.sent] == ["send_photos", "send_message"]
    assert bot.sent[1]["buttons"] == [("✅ Đăng", "ok:7:2"), ("❌ Không đăng", "no:7:2")]


def test_format_review_truncates_to_4000() -> None:
    text = format_review(_post(body="x" * 6000, guardrail_report={"flags": ["f"]}))
    assert len(text) <= 4000
    assert "…" in text
    assert "⚠️ Cần xem: f" in text and text.endswith("gõ góp ý.")
