"""Post persistence and the daily post state machine."""

import uuid
from datetime import date, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel
from sqlalchemy import CursorResult, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
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


def _in_day_window(day: date, now: datetime) -> bool:
    """True while `day` is local today and the day has not ended (DAY_END)."""
    local = local_now(now)
    return day == local.date() and local.time() < DAY_END


def _transition(db: Session, post_id: uuid.UUID, revision: int, **values: object) -> bool:
    """Atomically move a pending post at `revision` to new values; False if it changed."""
    result = db.execute(
        update(Post)
        .where(Post.id == post_id, Post.status == "pending", Post.revision == revision)
        .values(updated_at=clock.utcnow(), **values)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return bool(cast(CursorResult[Any], result).rowcount == 1)


def _reload(db: Session, post_id: uuid.UUID) -> None:
    post = db.get(Post, post_id)
    if post is not None:
        db.refresh(post)


def approve(
    db: Session, post_id: uuid.UUID, revision: int, now: datetime
) -> Literal["ok", "stale", "blocked"]:
    post = db.get(Post, post_id)
    if post is None or post.status != "pending" or post.revision != revision:
        return "stale"
    if not _in_day_window(post.day, now):
        return "stale"  # the day is over: the post expires, it is never published
    if post.blocking:
        return "blocked"
    # Conditional UPDATE: a concurrent expiry (tick thread) or new revision wins.
    ok = _transition(db, post_id, revision, status="approved", approved_at=now)
    _reload(db, post_id)
    return "ok" if ok else "stale"


def reject(db: Session, post_id: uuid.UUID, revision: int) -> Literal["ok", "stale"]:
    post = db.get(Post, post_id)
    if post is None or post.status != "pending" or post.revision != revision:
        return "stale"
    ok = _transition(db, post_id, revision, status="rejected")
    _reload(db, post_id)
    return "ok" if ok else "stale"


def due_for_publish(db: Session, now: datetime) -> list[Post]:
    """Approved posts of local today whose slot time has passed, until DAY_END."""
    local = local_now(now)
    if local.time() >= DAY_END:
        return []
    approved = db.scalars(
        select(Post).where(Post.status == "approved", Post.day == local.date())
    ).all()
    return [p for p in approved if publish_at(p.day, p.slot) <= now]  # type: ignore[arg-type]


def expire_open(db: Session, now: datetime) -> list[tuple[Post, str]]:
    """Expire open posts whose day is over; returns (post, previous_status) pairs."""
    local = local_now(now)
    today = local.date()
    day_over = local.time() >= DAY_END
    open_posts = db.scalars(
        select(Post).where(Post.status.in_(("drafting", "pending", "approved")))
    ).all()
    expired = [
        (p, p.status) for p in open_posts if p.day < today or (p.day == today and day_over)
    ]
    for p, _previous in expired:
        p.status = "expired"
    db.commit()
    return expired


def posts_for_day(db: Session, day: date) -> list[Post]:
    return list(db.scalars(select(Post).where(Post.day == day).order_by(Post.slot)).all())
