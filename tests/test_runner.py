import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from app.config import Settings
from app.runner import NullTelegram, acquire_single_instance, run
from app.telegram.bot import TelegramError


def test_second_instance_is_refused(tmp_path: Path) -> None:
    lock_path = tmp_path / "bestone.lock"
    first = acquire_single_instance(lock_path)
    assert first is not None
    try:
        assert acquire_single_instance(lock_path) is None
    finally:
        first.close()  # type: ignore[attr-defined]
    again = acquire_single_instance(lock_path)
    assert again is not None
    again.close()  # type: ignore[attr-defined]


def test_run_exits_zero_when_already_running(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, DATA_DIR=str(tmp_path), DATABASE_URL="sqlite://"
    )
    held = acquire_single_instance(tmp_path / "bestone.lock")
    assert held is not None
    try:
        assert run(settings, open_browser=False) == 0
    finally:
        held.close()  # type: ignore[attr-defined]
    log_text = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "đang chạy" in log_text
    # run() removes its handlers so the log file is not left open.
    assert not any(isinstance(h, RotatingFileHandler) for h in logging.getLogger().handlers)


def test_null_telegram_raises_telegram_error_without_network() -> None:
    bot = NullTelegram()
    with pytest.raises(TelegramError):
        bot.send_message("hi")
    with pytest.raises(TelegramError):
        bot.edit_buttons_removed(1)
