import logging
from datetime import datetime, timedelta
from typing import Literal

import httpx
from sqlalchemy import or_, orm, select

from app import clock
from app.config import get_settings
from app.db.models import Alert
from app.telegram.bot import TelegramBot, TelegramError

logger = logging.getLogger(__name__)

AlertLevel = Literal["info", "warn", "urgent"]

REDELIVER_WINDOW = timedelta(hours=24)
REDELIVER_GAP = timedelta(minutes=5)
REDELIVER_BATCH = 10


def _telegram_config() -> tuple[str, str] | None:
    settings = get_settings()
    token, chat_id = settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_ADMIN_CHAT_ID
    return (token, chat_id) if token and chat_id else None


def _deliver(config: tuple[str, str], message: str) -> bool:
    token, chat_id = config
    try:
        with httpx.Client(timeout=10) as client:
            TelegramBot(token, chat_id, client=client).send_message(message)
    except (TelegramError, httpx.HTTPError) as exc:
        # Log only the exception type: httpx messages can include the URL (and bot token).
        logger.warning("Telegram alert delivery failed: %s", type(exc).__name__)
        return False
    return True


def send_alert(db: orm.Session, level: AlertLevel, message: str) -> None:
    """Record an alert row and push it to Telegram when configured. Never raises."""
    config = _telegram_config()
    now = clock.utcnow()
    alert = Alert(
        level=level,
        channel="telegram" if config else "db",
        message=message,
        last_attempt_at=now if config else None,
    )
    db.add(alert)
    db.commit()
    if config is None or not _deliver(config, message):
        return
    alert.delivered_at = clock.utcnow()
    db.commit()


def redeliver_alerts(db: orm.Session, now: datetime) -> None:
    """Resend undelivered Telegram alerts from the last 24 h. Never raises.

    Oldest first, at most REDELIVER_BATCH per call, one attempt per alert per
    REDELIVER_GAP. Stops at the first failure (Telegram is probably unreachable).
    """
    try:
        config = _telegram_config()
        if config is None:
            return
        alerts = db.scalars(
            select(Alert)
            .where(
                Alert.channel == "telegram",
                Alert.delivered_at.is_(None),
                Alert.created_at >= now - REDELIVER_WINDOW,
                or_(Alert.last_attempt_at.is_(None), Alert.last_attempt_at <= now - REDELIVER_GAP),
            )
            .order_by(Alert.created_at)
            .limit(REDELIVER_BATCH)
        ).all()
        for alert in alerts:
            alert.last_attempt_at = now
            db.commit()
            if not _deliver(config, alert.message):
                return
            alert.delivered_at = now
            db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Alert redelivery failed: %s", type(exc).__name__)
