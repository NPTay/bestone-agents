from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content import research
from app.content.research import fetch_article, find_candidates, load_queries
from app.db.models import ResearchItem
from app.llm.client import FakeLLM, SearchHit

BODY = "Hầm chui mới được thi công với nhiều hạng mục chống thấm. " * 20


def _html(body: str = BODY) -> str:
    return (
        "<html><head><title>Tiêu đề</title><script>var secret=1;</script></head><body>"
        "<nav>menu rác</nav>"
        f"<article><style>.x{{}}</style><p>{body}</p><script>evil()</script></article>"
        "</body></html>"
    )


def _ok(body: str = BODY) -> httpx.Response:
    return httpx.Response(200, html=_html(body))


@respx.mock
def test_fetch_article_extracts_main_text_and_strips_scripts() -> None:
    respx.get("https://www.vnexpress.net/a").mock(return_value=_ok())
    art = fetch_article("https://www.vnexpress.net/a")
    assert art is not None
    assert art.source_name == "vnexpress.net"
    assert art.title == "Tiêu đề"
    assert "Hầm chui" in art.text
    assert "evil" not in art.text
    assert "secret" not in art.text
    assert "menu rác" not in art.text
    assert len(art.text) <= 8000


@respx.mock
def test_fetch_article_rejects_facebook_and_short_pages() -> None:
    fb = respx.get("https://www.facebook.com/x").mock(return_value=_ok())
    assert fetch_article("https://www.facebook.com/x") is None
    assert fb.call_count == 0
    respx.get("https://news.test/short").mock(return_value=_ok("ngắn"))
    assert fetch_article("https://news.test/short") is None
    respx.get("https://news.test/pdf").mock(
        return_value=httpx.Response(
            200, content=b"x" * 900, headers={"content-type": "application/pdf"}
        )
    )
    assert fetch_article("https://news.test/pdf") is None
    respx.get("https://news.test/err").mock(return_value=httpx.Response(500))
    assert fetch_article("https://news.test/err") is None


@respx.mock
def test_skips_already_used_urls(db: Session) -> None:
    db.add(
        ResearchItem(
            url="https://news.test/old",
            title="old",
            source_name="news.test",
            fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
    )
    db.commit()
    old = respx.get("https://news.test/old").mock(return_value=_ok())
    respx.get("https://news.test/new").mock(return_value=_ok())
    respx.get("https://news.test/bad").mock(return_value=httpx.Response(404))
    llm = FakeLLM(
        {},
        hits=[
            SearchHit(url="https://news.test/old", title="old"),
            SearchHit(url="https://news.test/bad", title="bad"),
            SearchHit(url="https://news.test/new", title="new"),
        ],
    )
    # FakeLLM returns the same hits for every query: in-run duplicates must be dropped.
    arts = find_candidates(llm, db, ["q1", "q2"], None, day=date(2026, 10, 13))
    assert [a.url for a in arts] == ["https://news.test/new"]
    assert old.call_count == 0
    urls = set(db.scalars(select(ResearchItem.url)))
    assert urls == {"https://news.test/old", "https://news.test/new"}


@respx.mock
def test_limit_is_respected(db: Session) -> None:
    for i in range(4):
        respx.get(f"https://news.test/{i}").mock(return_value=_ok())
    llm = FakeLLM({}, hits=[SearchHit(url=f"https://news.test/{i}", title="t") for i in range(4)])
    arts = find_candidates(llm, db, ["a", "b", "c"], None, day=date(2026, 10, 13), limit=3)
    assert len(arts) == 3
    assert len({a.url for a in arts}) == 3


def test_queries_rotate_by_day(db: Session) -> None:
    queries = [f"q{i}" for i in range(5)]
    day = date(2026, 10, 13)
    start = day.toordinal() % 5
    llm = FakeLLM({}, hits=[])
    find_candidates(llm, db, queries, None, day=day)
    assert [c["query"] for c in llm.calls] == [queries[(start + i) % 5] for i in range(3)]
    assert all(c["agent"] == "research" for c in llm.calls)
    llm2 = FakeLLM({}, hits=[])
    find_candidates(llm2, db, queries, None, day=date(2026, 10, 14))
    assert llm2.calls[0]["query"] == queries[(start + 1) % 5]


def test_load_queries_skips_blank_and_comments(tmp_path: Path) -> None:
    p = tmp_path / "q.txt"
    p.write_text("# c\n\n  hầm chui \nmetro\n", encoding="utf-8")
    assert load_queries(p) == ["hầm chui", "metro"]


@pytest.mark.parametrize(
    "url",
    [
        "https://baomoi.com/ham-chui-t36668660.epi",  # baomoi topic page (seen live 15/10)
        "https://vnexpress.net/tag/chong-tham-123",
        "https://baoxaydung.vn/chu-de/ham-chui",
        "https://example.vn/tim-kiem?q=ham",
    ],
)
@respx.mock  # any HTTP call would fail the test: listing pages must not be fetched
def test_listing_and_topic_pages_are_skipped(url: str) -> None:
    assert research.fetch_article(url) is None


def test_regular_baomoi_article_url_is_not_treated_as_listing() -> None:
    assert not research._is_listing("https://baomoi.com/ham-chui-an-phu-thong-xe-c50123456.epi")


def test_find_candidates_passes_news_domains_to_search(db: Session) -> None:
    llm = FakeLLM({}, hits=[])
    find_candidates(llm, db, ["q1"], None, day=date(2026, 10, 15), domains=["vnexpress.net"])
    assert all(c["allowed_domains"] == ["vnexpress.net"] for c in llm.calls)


def test_news_domains_config_lists_major_vietnamese_papers() -> None:
    root = Path(research.__file__).resolve().parents[2]
    domains = load_queries(root / "config" / "news_domains.txt")
    assert {"vnexpress.net", "tuoitre.vn", "baoxaydung.vn"} <= set(domains)


def _dated_html(head: str) -> str:
    return _html().replace("<head>", "<head>" + head)


@respx.mock
@pytest.mark.parametrize(
    "head",
    [
        '<meta name="pubdate" content="2026-10-08T14:00:00+07:00">',  # VnExpress
        '<meta property="article:published_time" content="2026-10-08T12:29:00">',  # Tuổi Trẻ
        '<script type="application/ld+json">{"datePublished": "2026-10-08T16:30:14.000+07:00"}'
        "</script>",  # VietNamNet
    ],
)
def test_fetch_article_reads_publish_date(head: str) -> None:
    page = httpx.Response(200, html=_dated_html(head))
    respx.get("https://vnexpress.net/a").mock(return_value=page)
    art = fetch_article("https://vnexpress.net/a")
    assert art is not None and art.published == date(2026, 10, 8)


@respx.mock
def test_fetch_article_without_date_has_none() -> None:
    respx.get("https://vnexpress.net/a").mock(return_value=_ok())
    art = fetch_article("https://vnexpress.net/a")
    assert art is not None and art.published is None


@respx.mock
def test_find_candidates_keeps_only_recent_dated_news(db: Session) -> None:
    def page(day: str) -> httpx.Response:
        return httpx.Response(
            200, html=_dated_html(f'<meta name="pubdate" content="{day}T08:00:00+07:00">')
        )

    respx.get("https://news.test/recent").mock(return_value=page("2026-09-01"))
    respx.get("https://news.test/old").mock(return_value=page("2026-06-01"))  # > 90 days
    respx.get("https://news.test/undated").mock(return_value=_ok())
    llm = FakeLLM(
        {},
        hits=[
            SearchHit(url="https://news.test/old", title="o"),
            SearchHit(url="https://news.test/undated", title="u"),
            SearchHit(url="https://news.test/recent", title="r"),
        ],
    )
    arts = find_candidates(llm, db, ["q"], None, day=date(2026, 10, 15), max_age_days=90)
    assert [a.url for a in arts] == ["https://news.test/recent"]
