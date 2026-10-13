import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Enum, Float, ForeignKey, Integer, Numeric, String, Text, Uuid
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
