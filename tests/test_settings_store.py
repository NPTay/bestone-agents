from collections.abc import Callable

import pytest
from sqlalchemy import orm, select

from app.config import get_settings
from app.db.models import AuditLog, Setting, User
from app.settings_store import get_autonomy, get_kill_switch, set_autonomy, set_kill_switch


def test_autonomy_default_and_invalid(db: orm.Session) -> None:
    assert get_autonomy(db) == "draft_only"
    db.add(Setting(key="AUTONOMY_LEVEL", value="yolo"))
    db.commit()
    assert get_autonomy(db) == "draft_only"


def test_autonomy_env_seed_only_when_row_missing(
    db: orm.Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTONOMY_LEVEL", "auto_safe")
    get_settings.cache_clear()
    try:
        assert get_autonomy(db) == "auto_safe"
        assert db.scalar(select(Setting).where(Setting.key == "AUTONOMY_LEVEL")) is None
        db.add(Setting(key="AUTONOMY_LEVEL", value="draft_only"))
        db.commit()
        assert get_autonomy(db) == "draft_only"
        monkeypatch.setenv("AUTONOMY_LEVEL", "bogus")
        get_settings.cache_clear()
        db.query(Setting).delete()
        db.commit()
        assert get_autonomy(db) == "draft_only"
    finally:
        get_settings.cache_clear()


def test_set_autonomy_audited(db: orm.Session, make_user: Callable[..., User]) -> None:
    user = make_user()
    set_autonomy(db, "auto_safe", user.id)
    assert get_autonomy(db) == "auto_safe"
    set_autonomy(db, "draft_only", user.id)
    assert get_autonomy(db) == "draft_only"
    rows = db.scalars(select(AuditLog).where(AuditLog.action == "autonomy_changed")).all()
    assert len(rows) == 2
    assert rows[0].actor == user.id


def test_set_autonomy_rejects_invalid(db: orm.Session) -> None:
    with pytest.raises(ValueError):
        set_autonomy(db, "yolo", None)  # type: ignore[arg-type]


def test_kill_switch(db: orm.Session, make_user: Callable[..., User]) -> None:
    user = make_user()
    assert get_kill_switch(db) is False
    set_kill_switch(db, True, user.id)
    assert get_kill_switch(db) is True
    set_kill_switch(db, False, user.id)
    assert get_kill_switch(db) is False
    actions = {a.action for a in db.scalars(select(AuditLog))}
    assert {"kill_switch_on", "kill_switch_off"} <= actions
    assert db.scalar(select(Setting.value).where(Setting.key == "KILL_SWITCH")) == "false"
