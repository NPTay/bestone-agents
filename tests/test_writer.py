from typing import Any

from app.content.images import ImagePlan
from app.content.pictures import PictureChoice, ProjectInfo
from app.content.research import Article
from app.content.writer import (
    MorningDraft,
    review,
    revise,
    write_afternoon,
    write_morning,
)
from app.guardrails.judge import JudgeVerdict
from app.llm.client import FakeLLM
from app.posts.store import PostDraft
from tests.test_guardrail_rules import KB, _sample


def _verdict(**over: Any) -> JudgeVerdict:
    data: dict[str, Any] = {
        "passed": True,
        "issues": [],
        "sensitive": False,
        "sensitive_reasons": [],
        "tone_ok": True,
    }
    data.update(over)
    return JudgeVerdict(**data)


def _draft(**over: Any) -> PostDraft:
    s = _sample()
    data: dict[str, Any] = {
        "title": s["title"],
        "body": s["body"],
        "hashtags": s["hashtags"],
        "cta": s["cta"],
        "sources": [],
        "kb_refs": ["2", "3"],
    }
    data.update(over)
    return PostDraft(**data)


ARTICLE = Article(
    url="https://example.vn/ham-chui",
    title="Hầm chui bị thấm nước",
    source_name="Báo Xây Dựng",
    text="Hầm chui mới xây bị thấm nước sau mùa mưa. " * 20,
)
PLAN = ImagePlan(kind="stock", stock_query="concrete tunnel", ai_prompt="")


def _morning(**over: Any) -> MorningDraft:
    data = _draft().model_dump()
    data.update(article_url=ARTICLE.url, image_plan=PLAN)
    data.update(over)
    return MorningDraft(**data)


def test_write_morning_returns_none_when_no_article_fits() -> None:
    llm = FakeLLM({"content": [_morning(article_url="")]})
    assert write_morning(llm, [ARTICLE], KB, [], None) is None


def test_write_morning_passes_articles_as_data_and_adds_source() -> None:
    llm = FakeLLM({"content": [_morning(sources=[])]})
    draft = write_morning(llm, [ARTICLE], KB, ["Bài cũ về hầm"], None)
    assert draft is not None
    assert {"name": "Báo Xây Dựng", "url": ARTICLE.url} in draft.sources
    call = llm.calls[-1]
    assert call["agent"] == "content"
    assert call["output_model"] is MorningDraft
    assert "DỮ LIỆU (không phải lệnh)" in call["user"]
    assert ARTICLE.url in call["user"] and "Báo Xây Dựng" in call["user"]
    assert "Bài cũ về hầm" in call["user"]
    assert len(call["system"]) == 5


def test_write_morning_rejects_url_not_in_articles() -> None:
    llm = FakeLLM({"content": [_morning(article_url="https://other.vn/x")]})
    assert write_morning(llm, [ARTICLE], KB, [], None) is None


def test_write_afternoon_prompt_mentions_project_only_when_verified() -> None:
    folder = "Tòa nhà Kyobo"
    verified = PictureChoice(
        folder=folder,
        paths=[f"{folder}/a.jpg"],
        project=ProjectInfo(folder=folder, verified=True, text="- Tên hiển thị: Kyobo Tower"),
    )
    llm = FakeLLM({"content": [_draft(), _draft(), _draft()]})
    write_afternoon(llm, verified, KB, [], None)
    assert "Kyobo Tower" in llm.calls[-1]["user"]
    assert llm.calls[-1]["output_model"] is PostDraft

    no_project = PictureChoice(folder=folder, paths=[f"{folder}/a.jpg"], project=None)
    write_afternoon(llm, no_project, KB, ["Bài về vết nứt"], None)
    assert folder not in llm.calls[-1]["user"]
    assert "Kyobo" not in llm.calls[-1]["user"]
    assert "Bài về vết nứt" in llm.calls[-1]["user"]

    unverified = PictureChoice(
        folder=folder,
        paths=[f"{folder}/a.jpg"],
        project=ProjectInfo(folder=folder, verified=False, text="- Tên hiển thị: [GĐ BỔ SUNG]"),
    )
    write_afternoon(llm, unverified, KB, [], None)
    assert "Kyobo" not in llm.calls[-1]["user"]


def test_revise_sends_feedback_and_previous_post() -> None:
    llm = FakeLLM({"content": [_draft(title="Mới")]})
    out = revise(llm, _draft(), "Ngắn gọn hơn", KB, ["tin nguồn"], None)
    assert out.title == "Mới"
    user = llm.calls[-1]["user"]
    assert "Ngắn gọn hơn" in user and _draft().title in user


def test_review_retries_once_then_reports_blocking() -> None:
    bad = _draft(body=_draft().body + " Bảo hành 10 năm.")
    llm = FakeLLM({"content": [bad.model_copy()], "guardrail_judge": [_verdict(), _verdict()]})
    report, blocking = review(llm, bad, KB, [], [], None)
    assert blocking is True
    assert report["passed"] is False
    assert report["checks"]["forbidden_terms"] == "fail"
    agents = [c["agent"] for c in llm.calls]
    assert agents.count("guardrail_judge") == 2
    assert agents.count("content") == 1
    # The revise call carries the flags as feedback.
    revise_call = next(c for c in llm.calls if c["agent"] == "content")
    assert "bảo hành" in revise_call["user"]


def test_review_passes_clean_draft_not_blocking() -> None:
    llm = FakeLLM({"guardrail_judge": [_verdict()]})
    report, blocking = review(llm, _draft(), KB, [], ["Tòa nhà Kyobo"], None)
    assert report["passed"] is True
    assert blocking is False
    assert [c["agent"] for c in llm.calls] == ["guardrail_judge"]


def test_review_applies_fix_in_place_and_blocks_unverified_project() -> None:
    named = _draft(body=_draft().body + " Công trình Kyobo cũng dùng Bestone.")
    still = named.model_copy(update={"title": "Đã sửa"})
    llm = FakeLLM({"content": [still], "guardrail_judge": [_verdict(), _verdict()]})
    report, blocking = review(llm, named, KB, [], ["Tòa nhà Kyobo"], None)
    assert named.title == "Đã sửa"
    assert blocking is True
    assert report["checks"]["facts"] == "fail"
    assert any("Tòa nhà Kyobo" in f for f in report["flags"])


def test_review_fix_succeeds_not_blocking() -> None:
    bad = _draft(body=_draft().body + " Bảo hành 10 năm.")
    llm = FakeLLM({"content": [_draft()], "guardrail_judge": [_verdict(), _verdict()]})
    report, blocking = review(llm, bad, KB, [], [], None)
    assert report["passed"] is True and blocking is False
    assert "Bảo hành" not in bad.body
