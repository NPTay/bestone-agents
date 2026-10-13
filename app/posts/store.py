"""Post persistence and the daily post state machine."""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Post
from app.guardrails.judge import GuardrailReport
from app.schedule_times import DAY_END, Slot, local_now, publish_at

PostStatus = Literal[
    "drafting",
    "pending",
    "approved",
    "publishing",
    "published",
    "rejected",
    "expired",
    "failed",
]


class PostDraft(BaseModel):
    title: str
    body: str
    hashtags: list[str]
    cta: str
    sources: list[dict[str, str]]
    kb_refs: list[str]


def claim_slot(db: Session, day: date, slot: Slot) -> Post | None:
    """Insert a `drafting` row for (day, slot); None if it already exists."""
    post = Post(day=day, slot=slot, status="drafting")
    db.add(post)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    return post


def _fill(post: Post, draft: PostDraft, report: GuardrailReport, blocking: bool) -> None:
    post.title = draft.title
    post.body = draft.body
    post.hashtags = list(draft.hashtags)
    post.cta = draft.cta
    post.sources = [dict(s) for s in draft.sources]
    post.kb_refs = list(draft.kb_refs)
    post.guardrail_report = dict(report)
    post.blocking = blocking


def save_draft(
    db: Session, post: Post, draft: PostDraft, report: GuardrailReport, blocking: bool
) -> None:
    _fill(post, draft, report, blocking)
    post.status = "pending"
    db.commit()


def new_revision(
    db: Session, post: Post, draft: PostDraft, report: GuardrailReport, blocking: bool
) -> None:
    _fill(post, draft, report, blocking)
    post.revision += 1
    post.status = "pending"
    db.commit()


def approve(
    db: Session, post_id: uuid.UUID, revision: int, now: datetime
) -> Literal["ok", "stale", "blocked"]:
    post = db.get(Post, post_id)
    if post is None or post.status != "pending" or post.revision != revision:
        return "stale"
    if post.blocking:
        return "blocked"
    post.status = "approved"
    post.approved_at = now
    db.commit()
    return "ok"


def reject(db: Session, post_id: uuid.UUID, revision: int) -> Literal["ok", "stale"]:
    post = db.get(Post, post_id)
    if post is None or post.status != "pending" or post.revision != revision:
        return "stale"
    post.status = "rejected"
    db.commit()
    return "ok"


def due_for_publish(db: Session, now: datetime) -> list[Post]:
    approved = db.scalars(select(Post).where(Post.status == "approved")).all()
    return [p for p in approved if publish_at(p.day, p.slot) <= now]  # type: ignore[arg-type]


def expire_open(db: Session, now: datetime) -> list[Post]:
    local = local_now(now)
    today = local.date()
    day_over = local.time() >= DAY_END
    open_posts = db.scalars(
        select(Post).where(Post.status.in_(("drafting", "pending", "approved")))
    ).all()
    expired = [p for p in open_posts if p.day < today or (p.day == today and day_over)]
    for p in expired:
        p.status = "expired"
    db.commit()
    return expired


def posts_for_day(db: Session, day: date) -> list[Post]:
    return list(db.scalars(select(Post).where(Post.day == day).order_by(Post.slot)).all())
