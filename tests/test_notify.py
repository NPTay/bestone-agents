import logging
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import orm

from app.config import get_settings
from app.db.models import Alert
from app.integrations.notify import send_alert

URL = r"https://api\.telegram\.org/bottok123/sendMessage"


@pytest.fixture
def telegram_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_send_alert_delivered(telegram_env: None, respx_mock, db: orm.Session) -> None:  # type: ignore[no-untyped-def]
    route = respx_mock.post(url__regex=URL).respond(200, json={"ok": True})
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
