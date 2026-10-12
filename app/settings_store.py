import uuid
from typing import Literal, get_args

from sqlalchemy import orm, select

from app.audit import write_audit
from app.config import get_settings
from app.db.models import Setting

AutonomyLevel = Literal["draft_only", "auto_safe", "auto_full"]
DEFAULT_AUTONOMY: AutonomyLevel = "draft_only"
_LEVELS: tuple[str, ...] = get_args(AutonomyLevel)
AUTONOMY_KEY = "AUTONOMY_LEVEL"
KILL_SWITCH_KEY = "KILL_SWITCH"


def _get(db: orm.Session, key: str) -> str | None:
    return db.scalar(select(Setting.value).where(Setting.key == key))


def _upsert(db: orm.Session, key: str, value: str) -> None:
    row = db.scalar(select(Setting).where(Setting.key == key))
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def _as_level(value: str | None) -> AutonomyLevel | None:
    if value == "draft_only":
        return "draft_only"
    if value == "auto_safe":
        return "auto_safe"
    if value == "auto_full":
        return "auto_full"
    return None


def get_autonomy(db: orm.Session) -> AutonomyLevel:
    """DB row wins; env only seeds when the row is missing. Invalid -> draft_only."""
    value = _get(db, AUTONOMY_KEY)
    if value is None:
        value = get_settings().AUTONOMY_LEVEL
    return _as_level(value) or DEFAULT_AUTONOMY


def set_autonomy(db: orm.Session, level: AutonomyLevel, actor_id: uuid.UUID | None) -> None:
    if level not in _LEVELS:
        raise ValueError(f"Invalid autonomy level: {level!r}")
    previous = get_autonomy(db)
    _upsert(db, AUTONOMY_KEY, level)
    write_audit(
        db, actor_id, "autonomy_changed", "setting", AUTONOMY_KEY, {"from": previous, "to": level}
    )
    db.commit()


def get_kill_switch(db: orm.Session) -> bool:
    return (_get(db, KILL_SWITCH_KEY) or "").strip().lower() == "true"


def set_kill_switch(db: orm.Session, on: bool, actor_id: uuid.UUID | None) -> None:
    _upsert(db, KILL_SWITCH_KEY, "true" if on else "false")
    write_audit(
        db, actor_id, "kill_switch_on" if on else "kill_switch_off", "setting", KILL_SWITCH_KEY, {}
    )
    db.commit()
