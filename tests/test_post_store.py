from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Post
from app.guardrails.judge import GuardrailReport
from app.posts import store
from app.posts.store import PostDraft
from app.schedule_times import LOCAL_TZ, Slot

D = date(2026, 10, 13)
REPORT: GuardrailReport = {"passed": True, "checks": {}, "flags": [], "sensitive": False}


def draft(title: str = "t") -> PostDraft:
    return PostDraft(title=title, body="b", hashtags=["#a"], cta="c", sources=[], kb_refs=["1"])


def local(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=LOCAL_TZ).astimezone(UTC)


def pending(db: Session, day: date = D, slot: Slot = "morning", blocking: bool = False) -> Post:
    post = store.claim_slot(db, day, slot)
    assert post is not None
    store.save_draft(db, post, draft(), REPORT, blocking)
    return post


def test_claim_slot_is_idempotent(db: Session) -> None:
    first = store.claim_slot(db, D, "morning")
    assert first is not None and first.status == "drafting"
    assert store.claim_slot(db, D, "morning") is None
    assert db.scalar(select(func.count()).select_from(Post)) == 1
    assert store.claim_slot(db, D, "afternoon") is not None


def test_approve_requires_matching_revision(db: Session) -> None:
    post = pending(db)
    store.new_revision(db, post, draft("v2"), REPORT, False)
    assert post.revision == 2 and post.status == "pending" and post.title == "v2"
    now = local(D, 8, 30)
    assert store.approve(db, post.id, 1, now) == "stale"
    assert post.status == "pending"
    assert store.approve(db, post.id, 2, now) == "ok"
    assert post.status == "approved" and post.approved_at == now


def test_approve_blocked_when_guardrail_blocking(db: Session) -> None:
    post = pending(db, blocking=True)
    assert store.approve(db, post.id, 1, local(D, 8, 30)) == "blocked"
    assert post.status == "pending"


def test_reject_after_publish_is_stale(db: Session) -> None:
    post = pending(db)
    post.status = "published"
    db.commit()
    assert store.reject(db, post.id, 1) == "stale"
    assert post.status == "published"


def test_reject_pending(db: Session) -> None:
    post = pending(db)
    assert store.reject(db, post.id, 2) == "stale"
    assert store.reject(db, post.id, 1) == "ok"
    assert post.status == "rejected"


def test_due_for_publish_respects_slot_time(db: Session) -> None:
    post = pending(db)
    assert store.approve(db, post.id, 1, local(D, 8, 0)) == "ok"
    assert store.due_for_publish(db, local(D, 8, 59)) == []
    assert store.due_for_publish(db, local(D, 9, 0)) == [post]


def test_expire_open_at_day_end(db: Session) -> None:
    today = pending(db)
    yesterday = pending(db, D - timedelta(days=1))
    done = pending(db, D, "afternoon")
    done.status = "published"
    db.commit()
    assert store.expire_open(db, local(D, 19, 59)) == [(yesterday, "pending")]
    assert today.status == "pending"
    assert store.expire_open(db, local(D, 20, 0)) == [(today, "pending")]
    assert today.status == "expired"
    assert done.status == "published"


def test_expire_open_reports_previous_status(db: Session) -> None:
    approved = pending(db)
    store.approve(db, approved.id, 1, local(D, 8, 30))
    drafting = store.claim_slot(db, D, "afternoon")
    assert drafting is not None
    result = store.expire_open(db, local(D, 20, 0))
    assert sorted((p.slot, prev) for p, prev in result) == [
        ("afternoon", "drafting"),
        ("morning", "approved"),
    ]
    assert approved.status == "expired" and drafting.status == "expired"


def test_posts_for_day(db: Session) -> None:
    pending(db)
    pending(db, D, "afternoon")
    pending(db, D + timedelta(days=1))
    assert {p.slot for p in store.posts_for_day(db, D)} == {"morning", "afternoon"}
