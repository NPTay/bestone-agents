from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import orm

from app.db.models import (
    Contact,
    Conversation,
    Message,
    ResearchItem,
    Role,
    User,
    UserSession,
)

EXPECTED = {
    "users", "sessions", "research_items", "posts", "post_metrics", "contacts",
    "conversations", "messages", "leads", "jobs", "alerts", "llm_usage", "settings",
    "audit_log",
}  # fmt: skip


def test_all_tables_exist(engine: sa.Engine) -> None:
    assert EXPECTED <= set(sa.inspect(engine).get_table_names())


def test_unique_constraints(db: orm.Session) -> None:
    db.add(User(username="a", password_hash="x", role=Role.giam_doc))
    db.commit()
    db.add(User(username="a", password_hash="y", role=Role.ke_toan))
    with pytest.raises(sa.exc.IntegrityError):
        db.commit()


def test_research_source_url_unique(db: orm.Session) -> None:
    db.add(ResearchItem(source_url="http://x", source_name="n", title="t"))
    db.commit()
    db.add(ResearchItem(source_url="http://x", source_name="n2", title="t2"))
    with pytest.raises(sa.exc.IntegrityError):
        db.commit()


def test_contact_psid_unique(db: orm.Session) -> None:
    db.add(Contact(fb_psid="1"))
    db.commit()
    db.add(Contact(fb_psid="1"))
    with pytest.raises(sa.exc.IntegrityError):
        db.commit()


def test_message_fb_mid_unique(db: orm.Session) -> None:
    c = Contact(fb_psid="1")
    db.add(c)
    db.flush()
    conv = Conversation(contact_id=c.id, channel="messenger")
    db.add(conv)
    db.flush()
    db.add(Message(conversation_id=conv.id, direction="in", sender="customer", fb_mid="m1"))
    db.commit()
    db.add(Message(conversation_id=conv.id, direction="in", sender="customer", fb_mid="m1"))
    with pytest.raises(sa.exc.IntegrityError):
        db.commit()


def test_session_token_hash_unique(db: orm.Session, make_user) -> None:  # type: ignore[no-untyped-def]
    u = make_user()
    exp = datetime(2026, 10, 13, tzinfo=UTC)
    db.add(UserSession(user_id=u.id, token_hash="h", expires_at=exp, last_seen_at=exp))
    db.commit()
    db.add(UserSession(user_id=u.id, token_hash="h", expires_at=exp, last_seen_at=exp))
    with pytest.raises(sa.exc.IntegrityError):
        db.commit()


def test_timestamps_are_aware_utc_and_use_clock(db: orm.Session, frozen_now) -> None:  # type: ignore[no-untyped-def]
    u = User(username="t", password_hash="x", role=Role.ke_toan)
    db.add(u)
    db.commit()
    db.expire_all()
    assert u.created_at.tzinfo is not None
    assert u.created_at == frozen_now.now
    frozen_now.advance(timedelta(hours=1))
    u.full_name = "New"
    db.commit()
    db.expire_all()
    assert u.updated_at == frozen_now.now
    assert u.updated_at.utcoffset() == timedelta(0)
