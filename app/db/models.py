import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin, UTCDateTime


class Role(enum.StrEnum):
    giam_doc = "giam_doc"
    ke_toan = "ke_toan"


def _enum(name: str, *values: str) -> Enum:
    return Enum(*values, name=name)


# Enum value sets (ASCII slugs so they are safe as Postgres enum labels).
TOPICS = ("ha_tang", "quy_dinh", "su_co_tham", "du_an_moi", "cong_nghe", "esg", "khac")
POST_STATUSES = (
    "idea", "draft", "guardrail_failed", "pending_approval", "approved",
    "scheduled", "published", "failed",
)  # fmt: skip


class User(TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(100), unique=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, name="user_role"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_failed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    totp_secret: Mapped[str | None] = mapped_column(String(64))  # reserved, unused


class UserSession(TimestampMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    remember_me: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(500))


class ResearchItem(TimestampMixin, Base):
    __tablename__ = "research_items"

    source_url: Mapped[str] = mapped_column(String(2000), unique=True)
    source_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(_enum("research_topic", *TOPICS), default="khac")
    relevance_score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    used_in_post_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("posts.id"))


class Post(TimestampMixin, Base):
    __tablename__ = "posts"
    __table_args__ = (Index("ix_posts_status_scheduled_at", "status", "scheduled_at"),)

    pillar: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    image_brief: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(String(2000))
    sources: Mapped[list[str]] = mapped_column(JSONType, default=list)
    kb_refs: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(_enum("post_status", *POST_STATUSES), default="draft")
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    guardrail_report: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    fb_post_id: Mapped[str | None] = mapped_column(String(100))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class PostMetric(TimestampMixin, Base):
    __tablename__ = "post_metrics"

    post_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("posts.id"), index=True)
    reach: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    reactions: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"

    fb_psid: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(100))  # never log in clear
    company: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(100))
    first_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_window_expires_at", "window_expires_at"),)

    contact_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contacts.id"), index=True)
    channel: Mapped[str] = mapped_column(_enum("conversation_channel", "messenger", "comment"))
    status: Mapped[str] = mapped_column(
        _enum("conversation_status", "open", "waiting_human", "closed"), default="open"
    )
    last_customer_msg_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    window_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # +24h


class Message(TimestampMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id"), index=True
    )
    direction: Mapped[str] = mapped_column(_enum("message_direction", "in", "out"))
    sender: Mapped[str] = mapped_column(_enum("message_sender", "customer", "ai", "human"))
    text: Mapped[str | None] = mapped_column(Text)
    fb_mid: Mapped[str | None] = mapped_column(String(200), unique=True)
    guardrail_report: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    draft: Mapped[bool] = mapped_column(Boolean, default=False)


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (Index("ix_leads_score_status", "score", "status"),)

    contact_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("contacts.id"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("conversations.id"))
    project_type: Mapped[str | None] = mapped_column(String(200))
    scale: Mapped[str | None] = mapped_column(String(200))
    stage: Mapped[str | None] = mapped_column(String(200))
    timeline: Mapped[str | None] = mapped_column(String(200))
    score: Mapped[str] = mapped_column(_enum("lead_score", "HOT", "WARM", "COLD", "SPAM"))
    summary: Mapped[str | None] = mapped_column(Text)
    score_reasons: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(
        _enum("lead_status", "new", "contacted", "won", "lost"), default="new"
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    alerted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"

    agent: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(
        _enum("job_status", "queued", "running", "done", "failed"), default="queued"
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Alert(TimestampMixin, Base):
    __tablename__ = "alerts"

    level: Mapped[str] = mapped_column(_enum("alert_level", "info", "warn", "urgent"))
    channel: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class LlmUsage(TimestampMixin, Base):
    __tablename__ = "llm_usage"

    agent: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(12, 6).with_variant(Float, "sqlite"), default=0)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("jobs.id"))


class Setting(TimestampMixin, Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), unique=True)
    value: Mapped[str] = mapped_column(Text)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"

    actor: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str | None] = mapped_column(String(100))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
