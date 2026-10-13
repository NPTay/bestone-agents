import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import orm

from app.config import get_settings
from app.db.models import Alert
from app.integrations.notify import redeliver_alerts, send_alert

URL = r"https://api\.telegram\.org/bottok123/sendMessage"


@pytest.fixture
def telegram_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_send_alert_delivered(telegram_env: None, respx_mock, db: orm.Session) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.post(url__regex=URL).respond(
        200, json={"ok": True, "result": {"message_id": 1}}
    )
    send_alert(db, "warn", "hello")
    row = db.query(Alert).one()
    assert row.level == "warn" and row.message == "hello" and row.delivered_at is not None
    assert route.called


def test_send_alert_telegram_500_swallowed(
    telegram_env: None,
    respx_mock,  # type: ignore[no-untyped-def]
    db: orm.Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    respx_mock.post(url__regex=URL).respond(500)
    send_alert(db, "urgent", "boom")
    assert db.query(Alert).one().delivered_at is None
    assert "tok123" not in caplog.text


def test_send_alert_network_error_swallowed(
    telegram_env: None,
    respx_mock,  # type: ignore[no-untyped-def]
    db: orm.Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    respx_mock.post(url__regex=URL).mock(side_effect=httpx.ConnectError("x"))
    send_alert(db, "info", "boom")
    assert db.query(Alert).one().delivered_at is None
    assert "tok123" not in caplog.text


def test_send_alert_without_telegram_config(
    db: orm.Session,
    monkeypatch: pytest.MonkeyPatch,
    respx_mock,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_settings.cache_clear()
    send_alert(db, "info", "quiet")
    assert db.query(Alert).one().delivered_at is None
    assert not respx_mock.calls


NOW = datetime(2026, 10, 13, 2, 0, tzinfo=UTC)


def _undelivered(
    db: orm.Session, message: str, age: timedelta, last_attempt: timedelta | None = None
) -> Alert:
    alert = Alert(
        level="warn",
        channel="telegram",
        message=message,
        created_at=NOW - age,
        last_attempt_at=None if last_attempt is None else NOW - last_attempt,
    )
    db.add(alert)
    db.commit()
    return alert


def _ok(respx_mock):  # type: ignore[no-untyped-def]
    return respx_mock.post(url__regex=URL).respond(
        200, json={"ok": True, "result": {"message_id": 1}}
    )


def test_send_alert_records_its_attempt(
    telegram_env: None, respx_mock, db: orm.Session, frozen_clock  # type: ignore[no-untyped-def]
) -> None:
    frozen_clock(NOW)
    respx_mock.post(url__regex=URL).respond(500)
    send_alert(db, "warn", "x")
    assert db.query(Alert).one().last_attempt_at == NOW


def test_redeliver_sends_undelivered_alert(
    telegram_env: None, respx_mock, db: orm.Session  # type: ignore[no-untyped-def]
) -> None:
    route = _ok(respx_mock)
    alert = _undelivered(db, "hello", timedelta(hours=1), timedelta(minutes=6))
    redeliver_alerts(db, NOW)
    assert alert.delivered_at == NOW and alert.last_attempt_at == NOW
    assert route.call_count == 1
    redeliver_alerts(db, NOW + timedelta(minutes=10))
    assert route.call_count == 1


def test_redeliver_skips_recent_attempt(
    telegram_env: None, respx_mock, db: orm.Session  # type: ignore[no-untyped-def]
) -> None:
    route = _ok(respx_mock)
    alert = _undelivered(db, "hello", timedelta(hours=1), timedelta(minutes=4))
    redeliver_alerts(db, NOW)
    assert not route.called and alert.delivered_at is None


def test_redeliver_ignores_alerts_older_than_24h_and_db_channel(
    telegram_env: None, respx_mock, db: orm.Session  # type: ignore[no-untyped-def]
) -> None:
    route = _ok(respx_mock)
    _undelivered(db, "old", timedelta(hours=24, minutes=1))
    quiet = _undelivered(db, "quiet", timedelta(hours=1))
    quiet.channel = "db"
    db.commit()
    redeliver_alerts(db, NOW)
    assert not route.called


def test_redeliver_oldest_first_capped_at_ten(
    telegram_env: None, respx_mock, db: orm.Session  # type: ignore[no-untyped-def]
) -> None:
    route = _ok(respx_mock)
    for i in range(12):
        _undelivered(db, f"m{i:02d}", timedelta(minutes=100 - i))
    redeliver_alerts(db, NOW)
    sent = [json.loads(c.request.content)["text"] for c in route.calls]
    assert sent == [f"m{i:02d}" for i in range(10)]


def test_redeliver_failure_never_raises_and_waits_five_minutes(
    telegram_env: None, respx_mock, db: orm.Session  # type: ignore[no-untyped-def]
) -> None:
    route = respx_mock.post(url__regex=URL).mock(side_effect=httpx.ConnectError("x"))
    alert = _undelivered(db, "hello", timedelta(hours=1))
    redeliver_alerts(db, NOW)
    assert alert.delivered_at is None and alert.last_attempt_at == NOW
    redeliver_alerts(db, NOW + timedelta(minutes=4))
    assert route.call_count == 1
    redeliver_alerts(db, NOW + timedelta(minutes=5))
    assert route.call_count == 2


def test_redeliver_without_telegram_config_does_nothing(
    db: orm.Session, monkeypatch: pytest.MonkeyPatch, respx_mock  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_settings.cache_clear()
    _undelivered(db, "hello", timedelta(hours=1))
    redeliver_alerts(db, NOW)
    assert not respx_mock.calls
