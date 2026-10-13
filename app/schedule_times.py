"""Fixed daily schedule (local time, Asia/Ho_Chi_Minh)."""

from datetime import UTC, date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

Slot = Literal["morning", "afternoon"]

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

MORNING_DRAFT = time(8, 0)
MORNING_PUBLISH = time(9, 0)
MORNING_CUTOFF = time(12, 0)
AFTERNOON_DRAFT = time(15, 0)
AFTERNOON_PUBLISH = time(16, 30)
DAY_END = time(20, 0)


def local_now(utc: datetime) -> datetime:
    """Convert an aware (or naive-UTC) datetime to local time."""
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=UTC)
    return utc.astimezone(LOCAL_TZ)


def publish_at(day: date, slot: Slot) -> datetime:
    """Scheduled publish moment of a slot, as a UTC datetime."""
    at = MORNING_PUBLISH if slot == "morning" else AFTERNOON_PUBLISH
    return datetime.combine(day, at, tzinfo=LOCAL_TZ).astimezone(UTC)
