"""News research for the morning post: web search, dedupe, article fetching."""

import logging
from dataclasses import dataclass
from datetime import date
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


def fetch_article(url: str) -> Article | None:
    """Download a page and extract its main text; None if unusable."""
    if _is_blocked(url):
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
    )


def find_candidates(
    llm: LLMClient,
    db: Session,
    queries: list[str],
    job_id: UUID | None,
    *,
    day: date,
    limit: int = 5,
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
        hits = llm.web_search(agent="research", query=query, max_uses=3, job_id=job_id)
        for hit in hits:
            if len(articles) >= limit:
                return articles
            if hit.url in known or hit.url in seen:
                continue
            seen.add(hit.url)
            article = fetch_article(hit.url)
            if article is None:
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
