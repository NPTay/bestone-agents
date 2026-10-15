"""News research for the morning post: web search, dedupe, article fetching."""

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.db.models import ResearchItem
from app.llm.client import LLMClient

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 8000
MIN_TEXT_CHARS = 500
QUERIES_PER_RUN = 3
FETCH_TIMEOUT_S = 15.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
BLOCKED_DOMAINS = ("facebook.com", "fb.com")


@dataclass(frozen=True)
class Article:
    url: str
    title: str
    source_name: str
    text: str
    published: date | None = None


_DATE_META = ("article:published_time", "og:article:published_time", "pubdate", "datepublished")
_LD_DATE = re.compile(r'"datePublished"\s*:\s*"(\d{4}-\d{2}-\d{2})')
_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _parse_day(value: str | None) -> date | None:
    match = _ISO_DAY.match((value or "").strip())
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def _published_date(soup: BeautifulSoup, html: str) -> date | None:
    """Publish date from meta tags (VnExpress, Tuổi Trẻ, CafeF...) or JSON-LD (VietNamNet)."""
    for meta in soup.find_all("meta"):
        key = str(meta.get("property") or meta.get("name") or meta.get("itemprop") or "")
        if key.lower() in _DATE_META:
            day = _parse_day(str(meta.get("content") or ""))
            if day:
                return day
    match = _LD_DATE.search(html)
    return _parse_day(match[1]) if match else None


def load_queries(path: Path) -> list[str]:
    """Read queries, one per line; skip blank lines and '#' comments."""
    queries: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            queries.append(stripped)
    return queries


def _hostname(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def _is_blocked(url: str) -> bool:
    host = _hostname(url)
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)


# Tag, topic and search pages mix many stories; a post retold from them is mush.
_LISTING_PATH = re.compile(
    r"/(tag|tags|chu-de|topic|topics|tim-kiem|search|category|danh-muc)(/|$)"
    r"|-t\d+\.epi$",  # baomoi.com topic pages (articles end in -c<digits>.epi)
    re.IGNORECASE,
)


def _is_listing(url: str) -> bool:
    return bool(_LISTING_PATH.search(urlparse(url).path))


def fetch_article(url: str) -> Article | None:
    """Download a page and extract its main text; None if unusable."""
    if _is_blocked(url) or _is_listing(url):
        return None
    try:
        resp = httpx.get(
            url,
            timeout=FETCH_TIMEOUT_S,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        logger.info("fetch failed for %s", _hostname(url))
        return None
    if "text/html" not in resp.headers.get("content-type", "").lower():
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    published = _published_date(soup, resp.text)
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = " ".join(root.get_text(separator=" ").split())
    if len(text) < MIN_TEXT_CHARS:
        return None
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""
    return Article(
        url=url,
        title=title or url,
        source_name=_hostname(url),
        text=text[:MAX_TEXT_CHARS],
        published=published,
    )


def _is_recent(article: Article, day: date, max_age_days: int) -> bool:
    """Undated pages are skipped too: an old story retold as news misleads readers."""
    return article.published is not None and article.published >= day - timedelta(max_age_days)


def find_candidates(
    llm: LLMClient,
    db: Session,
    queries: list[str],
    job_id: UUID | None,
    *,
    day: date,
    limit: int = 5,
    domains: list[str] | None = None,
    max_age_days: int | None = None,
) -> list[Article]:
    """Search 3 rotating queries, fetch unseen articles, record them as ResearchItems."""
    if not queries:
        return []
    start = day.toordinal() % len(queries)
    count = min(QUERIES_PER_RUN, len(queries))
    picked = [queries[(start + i) % len(queries)] for i in range(count)]

    known = set(db.scalars(select(ResearchItem.url)))
    seen: set[str] = set()
    articles: list[Article] = []
    for query in picked:
        hits = llm.web_search(
            agent="research", query=query, max_uses=3, job_id=job_id, allowed_domains=domains
        )
        for hit in hits:
            if len(articles) >= limit:
                return articles
            if hit.url in known or hit.url in seen:
                continue
            seen.add(hit.url)
            article = fetch_article(hit.url)
            if article is None:
                continue
            if max_age_days is not None and not _is_recent(article, day, max_age_days):
                continue
            db.add(
                ResearchItem(
                    url=hit.url,
                    title=article.title,
                    source_name=article.source_name,
                    fetched_at=clock.utcnow(),
                )
            )
            db.commit()
            articles.append(article)
    return articles
