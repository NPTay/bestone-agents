import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin, UTCDateTime


def _enum(name: str, *values: str) -> Enum:
    return Enum(*values, name=name)


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


class Post(TimestampMixin, Base):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("day", "slot", name="uq_posts_day_slot"),)

    day: Mapped[date] = mapped_column(Date)
    slot: Mapped[str] = mapped_column(_enum("post_slot", "morning", "afternoon"))
    status: Mapped[str] = mapped_column(
        _enum(
            "post_status",
            "drafting",
            "pending",
            "approved",
            "publishing",
            "published",
            "rejected",
            "expired",
            "failed",
        ),
        default="drafting",
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    cta: Mapped[str] = mapped_column(Text, default="")
    sources: Mapped[list[dict[str, str]]] = mapped_column(JSONType, default=list)
    kb_refs: Mapped[list[str]] = mapped_column(JSONType, default=list)
    # Absolute paths (controller ruling R1).
    image_paths: Mapped[list[str]] = mapped_column(JSONType, default=list)
    image_note: Mapped[str | None] = mapped_column(Text)
    picture_folder: Mapped[str | None] = mapped_column(String(500))
    research_url: Mapped[str | None] = mapped_column(Text)
    guardrail_report: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    fb_post_id: Mapped[str | None] = mapped_column(String(100))
    comment_id: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
    # Morning article text, kept so revisions can be fact-checked (ruling R7).
    source_text: Mapped[str | None] = mapped_column(Text)


class ResearchItem(TimestampMixin, Base):
    __tablename__ = "research_items"

    url: Mapped[str] = mapped_column(String(1000), unique=True)
    title: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(200))
    used_post_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("posts.id"))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PictureUse(TimestampMixin, Base):
    __tablename__ = "picture_uses"

    # Relative to PICTURE_DIR, forward slashes.
    path: Mapped[str] = mapped_column(String(1000), unique=True)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
